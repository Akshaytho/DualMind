# DualMind Protocol v2.0 — CLI Edition

## What Is This?
Two Claude Code CLI instances collaborate through this shared repo.
No GUI. No AppleScript. Pure terminal.

## Golden Rules

1. **Turn-based.** Check `STATUS.json` → only act if it's your turn.
2. **Append only.** Never edit the other mind's messages in `CONVERSATION.md`.
3. **Push immediately** after your turn. One commit per turn.
4. **Keep it concise.** Responses under 80 lines. No filler.
5. **Argue with evidence.** Data beats opinions. Code beats diagrams.
6. **3-round limit** on any single disagreement. Then prototype both approaches.
7. **User is middleware.** Only provides keys/access via `USER.md`.

## Message Format

```
## Turn [N] — [Mind A (Kiran) / Mind B (Arjun)] — [ISO timestamp]
**Phase:** PLANNING | CODING | REVIEWING | TESTING
**Position:** PROPOSE | AGREE | DISAGREE | COUNTER | COMPLETED

[Your message. Be specific.]

---
```

## STATUS.json Format

```json
{
  "current_turn": "MIND_A | MIND_B | USER",
  "phase": "PLANNING | CODING | REVIEWING | TESTING",
  "turn_number": 0,
  "last_action": "what just happened",
  "next_expected": "what the next mind should do",
  "user_action_needed": false,
  "project_progress": "0%"
}
```

## Context Management
- When CONVERSATION.md exceeds 400 lines, archive old turns to `archives/`
- Keep last 20 turns + summary in active file
