#!/bin/bash
# ============================================
# DualMind Bridge v3.0 — Production Grade
# - Tests gate: blocks next turn if tests fail
# - Rate limiter: max 20 turns/hour
# - Git recovery: auto-fixes dirty state
# - Usage tracking: logs every turn
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$SCRIPT_DIR/bridge.log"
SECRETS_FILE="$SCRIPT_DIR/.secrets"
TURNS_LOG="$SCRIPT_DIR/.turns_log"
POLL_INTERVAL=60
MAX_TURNS_PER_HOUR=20
COOLDOWN_BETWEEN_TURNS=10
MAX_FIX_ATTEMPTS=2

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" | tee -a "$LOG_FILE"; }

# Prerequisites
command -v claude &>/dev/null || { log "ERROR: claude CLI not found"; exit 1; }
[ -f "$SECRETS_FILE" ] || { log "ERROR: bridge/.secrets missing"; exit 1; }

GIT_TOKEN=$(cat "$SECRETS_FILE")
cd "$REPO_DIR" || exit 1
git remote set-url origin "https://Akshaytho:${GIT_TOKEN}@github.com/Akshaytho/DualMind.git" 2>/dev/null
git config user.email "bridge@dualmind.ai"
git config user.name "DualMind Bridge"

caffeinate -d &
CAF_PID=$!
trap 'kill $CAF_PID 2>/dev/null; log "Bridge stopped."; exit 0' EXIT INT TERM

log "==========================================="
log "DualMind Bridge v3.0 — Production Grade"
log "Max turns/hour: $MAX_TURNS_PER_HOUR"
log "Cooldown: ${COOLDOWN_BETWEEN_TURNS}s"
log "==========================================="

# --- Prompts ---

MIND_A_PROMPT='You are Kiran (Mind A) in DualMind.

CHECKLIST — follow in order:
1. Read STATUS.json — confirm it is your turn (MIND_A)
2. Read MEMORY.md — this is your persistent context
3. Read last 3 entries in CONVERSATION.md (tail -80 CONVERSATION.md)
4. Read ONLY the code files relevant to your current task (check MEMORY.md code map)
5. Read mind-a/PERSONALITY.md — this defines how you think

DO YOUR WORK — plan, code, review, or test as needed.

IF YOU WROTE CODE:
- Run: cd workspace && python -m pytest -x -q
- ALL tests MUST pass. If any fail, fix them before continuing.

DEVIL ADVOCATE: Before agreeing with Mind B, ask "what is the strongest argument AGAINST this?" Say it.

AFTER WORK:
- Append your turn to CONVERSATION.md (format in PROTOCOL.md, under 60 lines)
- Update STATUS.json: current_turn=MIND_B, increment turn_number
- Update MEMORY.md if you made decisions, found bugs, or learned patterns
- Run: git add -A && git commit -m "[Mind A] Turn N: desc" && git push origin main'

MIND_B_PROMPT='You are Arjun (Mind B) in DualMind.

CHECKLIST — follow in order:
1. Read STATUS.json — confirm it is your turn (MIND_B)
2. Read MEMORY.md — this is your persistent context
3. Read last 3 entries in CONVERSATION.md (tail -80 CONVERSATION.md)
4. Read ONLY the code files relevant to your current task (check MEMORY.md code map)
5. Read mind-b/PERSONALITY.md — this defines how you think

DO YOUR WORK — plan, code, review, or test as needed.

IF YOU WROTE CODE:
- Run: cd workspace && python -m pytest -x -q
- ALL tests MUST pass. If any fail, fix them before continuing.

DEVIL ADVOCATE: Before agreeing with Mind A, ask "what is the strongest argument AGAINST this?" Say it.

AFTER WORK:
- Append your turn to CONVERSATION.md (format in PROTOCOL.md, under 60 lines)
- Update STATUS.json: current_turn=MIND_A, increment turn_number
- Update MEMORY.md if you made decisions, found bugs, or learned patterns
- Run: git add -A && git commit -m "[Mind B] Turn N: desc" && git push origin main'

FIX_PROMPT='The tests are failing. Read the test output below and fix the code.
Run: cd workspace && python -m pytest -x -q
Fix ONLY the failing tests. Do not change passing tests.
After fixing, commit and push: git add -A && git commit -m "[Fix] Turn N: fix failing tests" && git push origin main'

# --- Functions ---

rate_limit_check() {
    touch "$TURNS_LOG"
    local ONE_HOUR_AGO=$(date -v-1H +%s 2>/dev/null || date -d '1 hour ago' +%s 2>/dev/null)
    local RECENT=$(awk -v cutoff="$ONE_HOUR_AGO" '$1 >= cutoff' "$TURNS_LOG" | wc -l | tr -d ' ')
    
    if [ "$RECENT" -ge "$MAX_TURNS_PER_HOUR" ]; then
        log "RATE LIMIT: $RECENT turns in last hour (max $MAX_TURNS_PER_HOUR). Pausing 10 min."
        sleep 600
        return 1
    fi
    log "Rate: $RECENT/$MAX_TURNS_PER_HOUR turns this hour"
    return 0
}

record_turn() {
    date +%s >> "$TURNS_LOG"
}

git_recover() {
    cd "$REPO_DIR"
    local STATUS=$(git status --porcelain 2>/dev/null)
    if [ -n "$STATUS" ]; then
        log "WARNING: Dirty git state. Cleaning..."
        git stash 2>/dev/null
        git checkout main 2>/dev/null
        git pull origin main --no-rebase 2>/dev/null
    fi
}

run_tests() {
    cd "$REPO_DIR/workspace"
    if [ -f "pyproject.toml" ] || [ -d "tests" ]; then
        log "Running tests..."
        local OUTPUT=$(python3 -m pytest -x -q 2>&1)
        local EXIT_CODE=$?
        log "Tests exit code: $EXIT_CODE"
        echo "$OUTPUT" | tail -5 | while read l; do log "  TEST: $l"; done
        return $EXIT_CODE
    fi
    return 0
}

run_mind() {
    local MIND_NAME=$1
    local PROMPT=$2
    
    cd "$REPO_DIR"
    log ">>> $MIND_NAME starting..."
    
    claude -p "$PROMPT" --dangerously-skip-permissions 2>&1 | tail -5 | while read l; do log "  $l"; done
    
    log ">>> $MIND_NAME finished. Verifying tests..."
    
    # Test gate
    if ! run_tests; then
        log "TESTS FAILED after $MIND_NAME. Attempting fix..."
        local ATTEMPT=1
        while [ $ATTEMPT -le $MAX_FIX_ATTEMPTS ]; do
            log "Fix attempt $ATTEMPT/$MAX_FIX_ATTEMPTS..."
            cd "$REPO_DIR"
            local TEST_OUTPUT=$(cd workspace && python3 -m pytest -x -q 2>&1)
            claude -p "$FIX_PROMPT

Test output:
$TEST_OUTPUT" --dangerously-skip-permissions 2>&1 | tail -3 | while read l; do log "  FIX: $l"; done
            
            if run_tests; then
                log "Tests fixed on attempt $ATTEMPT"
                break
            fi
            ATTEMPT=$((ATTEMPT + 1))
        done
        
        if [ $ATTEMPT -gt $MAX_FIX_ATTEMPTS ]; then
            log "CRITICAL: Tests still failing after $MAX_FIX_ATTEMPTS fix attempts. Pausing."
            return 1
        fi
    fi
    
    log ">>> $MIND_NAME turn complete. All tests passing."
    record_turn
    return 0
}

check_and_run() {
    cd "$REPO_DIR"
    [ -f "STATUS.json" ] || { log "No STATUS.json"; return 1; }

    local TURN=$(python3 -c "import json; print(json.load(open('STATUS.json'))['current_turn'])" 2>/dev/null)
    local NUM=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('turn_number','?'))" 2>/dev/null)
    local USR=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('user_action_needed',False))" 2>/dev/null)

    log "Turn $NUM | Current: $TURN | User: $USR"

    if [ "$USR" = "True" ]; then
        osascript -e 'display notification "DualMind needs input." with title "DualMind"' 2>/dev/null
        return 1
    fi

    rate_limit_check || return 1

    if [ "$TURN" = "MIND_A" ]; then
        run_mind "Mind A (Kiran)" "$MIND_A_PROMPT"
        return $?
    elif [ "$TURN" = "MIND_B" ]; then
        run_mind "Mind B (Arjun)" "$MIND_B_PROMPT"
        return $?
    fi
    return 1
}

# --- Main Loop ---

while true; do
    git_recover
    
    git fetch origin main 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse origin/main 2>/dev/null)
    [ "$LOCAL" != "$REMOTE" ] && { log "Pulling..."; git pull origin main --no-rebase 2>/dev/null; }

    # Run minds back-to-back
    KEEP=true
    while $KEEP; do
        KEEP=false
        if check_and_run; then
            sleep "$COOLDOWN_BETWEEN_TURNS"
            git pull origin main --no-rebase 2>/dev/null
            KEEP=true
        fi
    done

    sleep "$POLL_INTERVAL"
done
