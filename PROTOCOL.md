# DualMind Protocol v2.1

## Rules

1. **Turn-based.** Check STATUS.json → only act if it's your turn.
2. **Append only.** Never edit the other mind's messages in CONVERSATION.md.
3. **Test before pushing.** Run `cd workspace && python -m pytest -x -q` EVERY time you change code. If tests fail, fix them. NEVER push failing tests.
4. **Update MEMORY.md** when you make decisions, find bugs, or learn patterns.
5. **Read MEMORY.md every turn** — it's your shared brain across sessions.
6. **Keep responses under 60 lines** in CONVERSATION.md. Be concise.
7. **Argue with evidence.** Show code, show tests, show failure scenarios.
8. **3-round limit** on disagreements. Then prototype both approaches and let test results decide.
9. **User is middleware.** Only provides keys/access via USER.md.

## Per-Turn Checklist
1. Read: STATUS.json, MEMORY.md, last 3 turns of CONVERSATION.md
2. Read relevant code files (not everything — just what matters for this turn)
3. Do your work (plan / code / review / test)
4. If you wrote code: `cd workspace && python -m pytest -x -q` — ALL MUST PASS
5. Append your turn to CONVERSATION.md
6. Update STATUS.json (flip current_turn, increment turn_number)
7. Update MEMORY.md if you made decisions or found patterns
8. `git add -A && git commit -m "[Mind A/B] Turn N: desc" && git push origin main`

## Message Format
```
## Turn [N] — [Mind A (Kiran) / Mind B (Arjun)] — [timestamp]
**Phase:** PLANNING | CODING | REVIEWING | TESTING
**Tests:** [PASSED X/X | SKIPPED | NO CODE CHANGES]

[Your message]

---
```

## Devil's Advocate Rule
Before agreeing with the other mind, ask yourself: "What's the strongest argument AGAINST this approach?" If you can think of one, say it. Agreement without pushback is a failure mode.
