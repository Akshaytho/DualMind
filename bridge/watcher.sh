#!/bin/bash
# DualMind Bridge v2.1 — Claude Code CLI
# Runs both minds in sequence, no external trigger needed

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$SCRIPT_DIR/bridge.log"
SECRETS_FILE="$SCRIPT_DIR/.secrets"
POLL_INTERVAL=60

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
log "DualMind Bridge v2.1 — CLI Edition"
log "==========================================="

MIND_A='You are Kiran (Mind A, The Pragmatist) in DualMind. Read PROTOCOL.md, mind-a/PERSONALITY.md, TASK.md, STATUS.json, CONVERSATION.md, DECISIONS.md. If current_turn is MIND_A: respond as Kiran. Append turn to CONVERSATION.md. Update STATUS.json (current_turn=MIND_B, increment turn_number). Run: git add -A && git commit -m "[Mind A] Turn N: desc" && git push origin main. Be concise, under 80 lines.'

MIND_B='You are Arjun (Mind B, The Architect) in DualMind. Read PROTOCOL.md, mind-b/PERSONALITY.md, TASK.md, STATUS.json, CONVERSATION.md, DECISIONS.md. If current_turn is MIND_B: respond as Arjun. Append turn to CONVERSATION.md. Update STATUS.json (current_turn=MIND_A, increment turn_number). Run: git add -A && git commit -m "[Mind B] Turn N: desc" && git push origin main. Be concise, under 80 lines.'

run_turn() {
    local TURN=$(python3 -c "import json; d=json.load(open('STATUS.json')); print(d['current_turn'])" 2>/dev/null)
    local NUM=$(python3 -c "import json; d=json.load(open('STATUS.json')); print(d.get('turn_number','?'))" 2>/dev/null)
    local USR=$(python3 -c "import json; d=json.load(open('STATUS.json')); print(d.get('user_action_needed',False))" 2>/dev/null)

    log "Turn $NUM | Current: $TURN | User: $USR"

    if [ "$USR" = "True" ]; then
        osascript -e 'display notification "DualMind needs input." with title "DualMind"' 2>/dev/null
        return 1
    fi

    if [ "$TURN" = "MIND_A" ]; then
        log ">>> Mind A (Kiran) starting..."
        claude -p "$MIND_A" --dangerously-skip-permissions 2>&1 | tail -3 | while read l; do log "  A: $l"; done
        log ">>> Mind A done"
        return 0
    elif [ "$TURN" = "MIND_B" ]; then
        log ">>> Mind B (Arjun) starting..."
        claude -p "$MIND_B" --dangerously-skip-permissions 2>&1 | tail -3 | while read l; do log "  B: $l"; done
        log ">>> Mind B done"
        return 0
    fi
    return 1
}

while true; do
    git fetch origin main 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse origin/main 2>/dev/null)
    [ "$LOCAL" != "$REMOTE" ] && { log "Pulling..."; git pull origin main --no-rebase 2>/dev/null; }

    # Run minds back-to-back until no more work
    KEEP=true
    while $KEEP; do
        KEEP=false
        if run_turn; then
            sleep 5
            git pull origin main --no-rebase 2>/dev/null
            KEEP=true
        fi
    done

    sleep "$POLL_INTERVAL"
done
