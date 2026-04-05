#!/bin/bash
# ============================================
# DualMind Bridge v3.0 — Production Grade
# - Test gate: pytest must pass between turns
# - Rate limiter: max 20 turns/hour
# - Git recovery: checks state before/after
# - Usage tracking: logs turns and time
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$SCRIPT_DIR/bridge.log"
SECRETS_FILE="$SCRIPT_DIR/.secrets"
POLL_INTERVAL=60
COOLDOWN=30
MAX_TURNS_PER_HOUR=20
TURN_COUNT_FILE="$SCRIPT_DIR/.turn_count"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" | tee -a "$LOG_FILE"; }

command -v claude &>/dev/null || { log "ERROR: claude CLI not found"; exit 1; }
[ -f "$SECRETS_FILE" ] || { log "ERROR: bridge/.secrets missing"; exit 1; }

GIT_TOKEN=$(cat "$SECRETS_FILE")
cd "$REPO_DIR" || exit 1
git remote set-url origin "https://Akshaytho:${GIT_TOKEN}@github.com/Akshaytho/DualMind.git" 2>/dev/null

caffeinate -d &
CAF_PID=$!
trap 'kill $CAF_PID 2>/dev/null; log "Bridge stopped."; exit 0' EXIT INT TERM

log "==========================================="
log "DualMind Bridge v3.0 — Production Grade"
log "Rate limit: $MAX_TURNS_PER_HOUR turns/hour"
log "Cooldown: ${COOLDOWN}s between turns"
log "Test gate: ENABLED"
log "==========================================="

# --- Rate Limiter ---
check_rate_limit() {
    local NOW=$(date +%s)
    local HOUR_AGO=$((NOW - 3600))
    
    # Clean old entries and count recent
    if [ -f "$TURN_COUNT_FILE" ]; then
        local COUNT=$(awk -v cutoff="$HOUR_AGO" '$1 > cutoff' "$TURN_COUNT_FILE" | wc -l | tr -d ' ')
        if [ "$COUNT" -ge "$MAX_TURNS_PER_HOUR" ]; then
            log "RATE LIMIT: $COUNT turns in last hour (max $MAX_TURNS_PER_HOUR). Cooling down."
            return 1
        fi
    fi
    return 0
}

record_turn() {
    echo "$(date +%s)" >> "$TURN_COUNT_FILE"
    # Clean entries older than 1 hour
    local HOUR_AGO=$(($(date +%s) - 3600))
    if [ -f "$TURN_COUNT_FILE" ]; then
        awk -v cutoff="$HOUR_AGO" '$1 > cutoff' "$TURN_COUNT_FILE" > "${TURN_COUNT_FILE}.tmp"
        mv "${TURN_COUNT_FILE}.tmp" "$TURN_COUNT_FILE"
    fi
}

# --- Test Gate ---
run_tests() {
    log "Running pytest..."
    cd "$REPO_DIR/workspace"
    
    if [ ! -f "pyproject.toml" ] && [ ! -f "setup.py" ]; then
        log "No project config found — skipping tests"
        return 0
    fi
    
    # Install deps quietly if needed
    pip install -e ".[dev]" --quiet 2>/dev/null || pip install -e . --quiet 2>/dev/null || true
    
    local TEST_OUTPUT=$(python -m pytest -x --tb=short 2>&1)
    local TEST_EXIT=$?
    
    # Extract pass/fail counts
    local SUMMARY=$(echo "$TEST_OUTPUT" | tail -1)
    log "Tests: $SUMMARY"
    
    if [ $TEST_EXIT -ne 0 ]; then
        log "TESTS FAILED — blocking next turn"
        # Update STATUS to make same mind fix tests
        cd "$REPO_DIR"
        python3 -c "
import json
with open('STATUS.json', 'r') as f:
    d = json.load(f)
d['phase'] = 'FIX_TESTS'
d['tests_passing'] = False
d['next_expected'] = 'Fix failing tests before proceeding'
with open('STATUS.json', 'w') as f:
    json.dump(d, f, indent=2)
"
        return 1
    fi
    
    # Update test count in STATUS
    cd "$REPO_DIR"
    python3 -c "
import json, re
summary = '''$SUMMARY'''
passed = re.search(r'(\d+) passed', summary)
count = int(passed.group(1)) if passed else 0
with open('STATUS.json', 'r') as f:
    d = json.load(f)
d['tests_passing'] = True
d['test_count'] = count
with open('STATUS.json', 'w') as f:
    json.dump(d, f, indent=2)
"
    return 0
}

# --- Git Recovery ---
check_git_state() {
    cd "$REPO_DIR"
    local STATUS=$(git status --porcelain 2>/dev/null)
    if [ -n "$STATUS" ]; then
        log "WARNING: Dirty git state detected. Cleaning..."
        git stash 2>/dev/null
        git checkout main 2>/dev/null
    fi
    return 0
}

# --- Mind Prompts ---
MIND_A='You are Kiran (Mind A, The Startup Founder) in DualMind.

STEP 1: Read these files ONLY: STATUS.json, CONVERSATION.md (last 50 lines: tail -50 CONVERSATION.md), MEMORY.md, mind-a/PERSONALITY.md, DECISIONS.md
STEP 2: Read ONLY the workspace files relevant to your current task (check STATUS.json next_expected)
STEP 3: If current_turn is MIND_A and phase is FIX_TESTS — run cd workspace && python -m pytest -x --tb=short, fix failures, and do NOT change turn
STEP 4: If current_turn is MIND_A and phase is not FIX_TESTS — respond as Kiran:
  - Find AT LEAST ONE thing to push back on (mandatory)
  - If coding: write tests FIRST, then implementation
  - After any code change: run cd workspace && python -m pytest -x --tb=short
  - If tests pass: append turn to CONVERSATION.md, update STATUS.json (current_turn=MIND_B, increment turn_number), update MEMORY.md if you learned something
  - If tests fail: fix them, do not change turn
STEP 5: git add -A && git commit -m "[Mind A] Turn N: desc" && git push origin main

MANDATORY: Include "Tests: X passed" and "Pushback: [your challenge]" in your CONVERSATION.md entry. Under 80 lines.'

MIND_B='You are Arjun (Mind B, The Systems Engineer) in DualMind.

STEP 1: Read these files ONLY: STATUS.json, CONVERSATION.md (last 50 lines: tail -50 CONVERSATION.md), MEMORY.md, mind-b/PERSONALITY.md, DECISIONS.md
STEP 2: Read ONLY the workspace files relevant to your current task (check STATUS.json next_expected)
STEP 3: If current_turn is MIND_B and phase is FIX_TESTS — run cd workspace && python -m pytest -x --tb=short, fix failures, and do NOT change turn
STEP 4: If current_turn is MIND_B and phase is not FIX_TESTS — respond as Arjun:
  - Find AT LEAST ONE thing to push back on (mandatory)
  - When reviewing code: check error handling, edge cases, naming, types
  - After any code change: run cd workspace && python -m pytest -x --tb=short
  - If tests pass: append turn to CONVERSATION.md, update STATUS.json (current_turn=MIND_A, increment turn_number), update MEMORY.md if you learned something
  - If tests fail: fix them, do not change turn
STEP 5: git add -A && git commit -m "[Mind B] Turn N: desc" && git push origin main

MANDATORY: Include "Tests: X passed" and "Pushback: [your challenge]" in your CONVERSATION.md entry. Under 80 lines.'

# --- Main Turn Runner ---
run_turn() {
    # Rate check
    check_rate_limit || return 1
    
    # Git health check
    check_git_state
    
    # Read status
    local TURN=$(python3 -c "import json; print(json.load(open('STATUS.json'))['current_turn'])" 2>/dev/null)
    local NUM=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('turn_number','?'))" 2>/dev/null)
    local PHASE=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('phase','?'))" 2>/dev/null)
    local USR=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('user_action_needed',False))" 2>/dev/null)
    local TESTS=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('tests_passing',True))" 2>/dev/null)

    log "Turn $NUM | Mind: $TURN | Phase: $PHASE | Tests: $TESTS | User: $USR"

    [ "$USR" = "True" ] && { log "User action needed — pausing"; return 1; }

    local START_TIME=$(date +%s)

    if [ "$TURN" = "MIND_A" ]; then
        log ">>> Mind A (Kiran) starting..."
        cd "$REPO_DIR"
        claude -p "$MIND_A" --dangerously-skip-permissions 2>&1 | tail -5 | while read l; do log "  A: $l"; done
    elif [ "$TURN" = "MIND_B" ]; then
        log ">>> Mind B (Arjun) starting..."
        cd "$REPO_DIR"
        claude -p "$MIND_B" --dangerously-skip-permissions 2>&1 | tail -5 | while read l; do log "  B: $l"; done
    else
        return 1
    fi

    local END_TIME=$(date +%s)
    local DURATION=$((END_TIME - START_TIME))
    log ">>> Completed in ${DURATION}s"

    # Verify tests independently
    cd "$REPO_DIR"
    git pull origin main --no-rebase 2>/dev/null
    run_tests
    local TEST_RESULT=$?

    if [ $TEST_RESULT -ne 0 ]; then
        log ">>> Tests failed after turn — same mind must fix"
        git add -A && git commit -m "[Bridge] Tests failed — flagging for fix" && git push origin main 2>/dev/null
    fi

    record_turn
    return 0
}

# --- Main Loop ---
while true; do
    git fetch origin main 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse origin/main 2>/dev/null)
    [ "$LOCAL" != "$REMOTE" ] && { log "Pulling..."; git pull origin main --no-rebase 2>/dev/null; }

    KEEP=true
    while $KEEP; do
        KEEP=false
        if run_turn; then
            sleep "$COOLDOWN"
            git pull origin main --no-rebase 2>/dev/null
            KEEP=true
        fi
    done

    sleep "$POLL_INTERVAL"
done
