#!/bin/bash
# ============================================
# DualMind Bridge v2 — Claude Code CLI Edition
# No AppleScript. No GUI. Pure terminal.
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$SCRIPT_DIR/bridge.log"
SECRETS_FILE="$SCRIPT_DIR/.secrets"
POLL_INTERVAL=60

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" | tee -a "$LOG_FILE"
}

# Check prerequisites
if ! command -v claude &> /dev/null; then
    log "ERROR: Claude Code CLI not found. Install: curl -fsSL https://claude.ai/install.sh | bash"
    exit 1
fi

if [ ! -f "$SECRETS_FILE" ]; then
    log "ERROR: bridge/.secrets not found. Create it with your GitHub token."
    exit 1
fi

GIT_TOKEN=$(cat "$SECRETS_FILE")

# Set up git auth
cd "$REPO_DIR" || exit 1
git remote set-url origin "https://Akshaytho:${GIT_TOKEN}@github.com/Akshaytho/DualMind.git" 2>/dev/null

# Keep Mac awake
caffeinate -d &
CAFFEINATE_PID=$!

cleanup() {
    kill $CAFFEINATE_PID 2>/dev/null
    log "Bridge stopped."
    exit 0
}
trap cleanup EXIT INT TERM

log "==========================================="
log "DualMind Bridge v2 — CLI Edition"
log "Repo: $REPO_DIR"
log "Poll: ${POLL_INTERVAL}s"
log "==========================================="

git rev-parse HEAD > "$SCRIPT_DIR/.last_hash" 2>/dev/null

MIND_A_PROMPT='You are Kiran (Mind A — The Pragmatist) in DualMind. 

Read these files: PROTOCOL.md, mind-a/PERSONALITY.md, TASK.md, STATUS.json, CONVERSATION.md, DECISIONS.md

If current_turn in STATUS.json is "MIND_A":
1. Read the latest conversation and any code changes
2. Respond as Kiran — concise, practical, evidence-based
3. Append your turn to CONVERSATION.md following the format in PROTOCOL.md
4. Update STATUS.json: set current_turn to "MIND_B", increment turn_number
5. Run: git add -A && git commit -m "[Mind A] Turn N: brief desc" && git push origin main

Keep response under 80 lines. If current_turn is not MIND_A, say "Not my turn" and exit.'

MIND_B_PROMPT='You are Arjun (Mind B — The Architect) in DualMind.

Read these files: PROTOCOL.md, mind-b/PERSONALITY.md, TASK.md, STATUS.json, CONVERSATION.md, DECISIONS.md

If current_turn in STATUS.json is "MIND_B":
1. Read the latest conversation and any code changes
2. Respond as Arjun — thorough, well-structured, systems-thinking
3. Append your turn to CONVERSATION.md following the format in PROTOCOL.md
4. Update STATUS.json: set current_turn to "MIND_A", increment turn_number
5. Run: git add -A && git commit -m "[Mind B] Turn N: brief desc" && git push origin main

Keep response under 80 lines. If current_turn is not MIND_B, say "Not my turn" and exit.'

while true; do
    git fetch origin main 2>/dev/null

    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse origin/main 2>/dev/null)

    if [ "$LOCAL" != "$REMOTE" ]; then
        log "Changes detected. Pulling..."
        git pull origin main --no-rebase 2>/dev/null

        if [ -f "STATUS.json" ]; then
            TURN=$(python3 -c "import json; print(json.load(open('STATUS.json'))['current_turn'])" 2>/dev/null)
            TURN_NUM=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('turn_number','?'))" 2>/dev/null)
            USER_NEEDED=$(python3 -c "import json; print(json.load(open('STATUS.json')).get('user_action_needed',False))" 2>/dev/null)

            log "Turn $TURN_NUM | Current: $TURN | User needed: $USER_NEEDED"

            if [ "$USER_NEEDED" = "True" ]; then
                osascript -e 'display notification "DualMind needs input. Check USER.md." with title "DualMind"' 2>/dev/null
                log "User action required — skipping"

            elif [ "$TURN" = "MIND_A" ]; then
                log "Running Mind A (Kiran) via Claude Code CLI..."
                cd "$REPO_DIR"
                claude -p "$MIND_A_PROMPT" --dangerously-skip-permissions 2>&1 | tail -5 | while read line; do log "  A: $line"; done
                log "Mind A completed"

            elif [ "$TURN" = "MIND_B" ]; then
                log "Running Mind B (Arjun) via Claude Code CLI..."
                cd "$REPO_DIR"
                claude -p "$MIND_B_PROMPT" --dangerously-skip-permissions 2>&1 | tail -5 | while read line; do log "  B: $line"; done
                log "Mind B completed"
            fi
        fi

        git rev-parse HEAD > "$SCRIPT_DIR/.last_hash"
    fi

    sleep "$POLL_INTERVAL"
done
