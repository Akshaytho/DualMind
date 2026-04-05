#!/bin/bash
# DualMind Bridge v3.0 — Idea Generation Mode

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$SCRIPT_DIR/bridge.log"
SECRETS_FILE="$SCRIPT_DIR/.secrets"
TURNS_LOG="$SCRIPT_DIR/.turns_log"
POLL_INTERVAL=90
MAX_TURNS_PER_HOUR=15
COOLDOWN_BETWEEN_TURNS=15

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" | tee -a "$LOG_FILE"; }

command -v claude &>/dev/null || { log "ERROR: claude not found"; exit 1; }
[ -f "$SECRETS_FILE" ] || { log "ERROR: .secrets missing"; exit 1; }

GIT_TOKEN=$(cat "$SECRETS_FILE")
cd "$REPO_DIR" || exit 1
git remote set-url origin "https://Akshaytho:${GIT_TOKEN}@github.com/Akshaytho/DualMind.git" 2>/dev/null
git config user.email "bridge@dualmind.ai"
git config user.name "DualMind Bridge"

caffeinate -d &
CAF_PID=$!
trap 'kill $CAF_PID 2>/dev/null; log "Bridge stopped."; exit 0' EXIT INT TERM

log "==========================================="
log "DualMind Bridge v3.0 — Idea Generation"
log "Rate: max $MAX_TURNS_PER_HOUR/hour"
log "==========================================="

MIND_A='You are Kiran (Mind A, The Market Hunter) in DualMind.

1. Read STATUS.json — confirm your turn
2. Read MEMORY.md — check killed ideas and criteria
3. Read last entries in CONVERSATION.md
4. Read mind-a/PERSONALITY.md and TASK.md

YOUR JOB: Find ideas nobody has built. For EVERY idea you propose:
- Use web search to verify it does not exist. Search product names, competitors, similar tools.
- If you find ANYTHING similar, KILL the idea and move on.
- Explain: who pays, what is the moat, why now, why Akshay.

DEVIL ADVOCATE: Before agreeing with Mind B on any idea, find the strongest argument against it.

After your turn:
- Append to CONVERSATION.md (under 60 lines, format per PROTOCOL.md)
- Update STATUS.json (current_turn=MIND_B, increment turn_number)
- Update MEMORY.md with ideas discussed and killed
- git add -A && git commit -m "[Mind A] Turn N: desc" && git push origin main'

MIND_B='You are Arjun (Mind B, The Systems Thinker) in DualMind.

1. Read STATUS.json — confirm your turn
2. Read MEMORY.md — check killed ideas and criteria
3. Read last entries in CONVERSATION.md
4. Read mind-b/PERSONALITY.md and TASK.md

YOUR JOB: Find ideas nobody has built. For EVERY idea you propose:
- Use web search to verify it does not exist. Search product names, competitors, similar tools.
- If you find ANYTHING similar, KILL the idea and move on.
- Explain: what is the network effect, what data compounds, what is the wedge.

DEVIL ADVOCATE: Before agreeing with Mind A on any idea, find the strongest argument against it.

After your turn:
- Append to CONVERSATION.md (under 60 lines, format per PROTOCOL.md)
- Update STATUS.json (current_turn=MIND_A, increment turn_number)
- Update MEMORY.md with ideas discussed and killed
- git add -A && git commit -m "[Mind B] Turn N: desc" && git push origin main'

rate_limit_check() {
    touch "$TURNS_LOG"
    local ONE_HOUR_AGO=$(date -v-1H +%s 2>/dev/null || date -d '1 hour ago' +%s 2>/dev/null)
    local RECENT=$(awk -v cutoff="$ONE_HOUR_AGO" '$1 >= cutoff' "$TURNS_LOG" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$RECENT" -ge "$MAX_TURNS_PER_HOUR" ]; then
        log "RATE LIMIT: $RECENT turns this hour. Pausing 10 min."
        sleep 600
        return 1
    fi
    log "Rate: $RECENT/$MAX_TURNS_PER_HOUR this hour"
    return 0
}

run_turn() {
    cd "$REPO_DIR"
    [ -f "STATUS.json" ] || return 1

    local TURN=$(python3 -c "import json; print(json.load(open('STATUS.json'))['current_turn'])" 2>/dev/null)
    local NUM=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('turn_number','?'))" 2>/dev/null)
    local USR=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('user_action_needed',False))" 2>/dev/null)

    log "Turn $NUM | Current: $TURN | User: $USR"

    [ "$USR" = "True" ] && { log "User action needed — pausing"; return 1; }
    rate_limit_check || return 1

    if [ "$TURN" = "MIND_A" ]; then
        log ">>> Mind A (Kiran) starting..."
        claude -p "$MIND_A" --dangerously-skip-permissions 2>&1 | tail -5 | while read l; do log "  A: $l"; done
        log ">>> Mind A done"
        date +%s >> "$TURNS_LOG"
        return 0
    elif [ "$TURN" = "MIND_B" ]; then
        log ">>> Mind B (Arjun) starting..."
        claude -p "$MIND_B" --dangerously-skip-permissions 2>&1 | tail -5 | while read l; do log "  B: $l"; done
        log ">>> Mind B done"
        date +%s >> "$TURNS_LOG"
        return 0
    fi
    return 1
}

# --- Main Loop ---
while true; do
    cd "$REPO_DIR"
    git fetch origin main 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse origin/main 2>/dev/null)
    [ "$LOCAL" != "$REMOTE" ] && { log "Pulling..."; git pull origin main --no-rebase 2>/dev/null; }

    KEEP=true
    while $KEEP; do
        KEEP=false
        if run_turn; then
            sleep "$COOLDOWN_BETWEEN_TURNS"
            git pull origin main --no-rebase 2>/dev/null
            KEEP=true
        fi
    done

    sleep "$POLL_INTERVAL"
done
