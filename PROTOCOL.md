# DualMind Protocol v2.1

## Golden Rules

1. **Turn-based.** Check STATUS.json → only act if it's your turn.
2. **Test everything.** After coding, run `cd workspace && python -m pytest -x --tb=short`. Fix failures before committing. The bridge will also verify.
3. **Challenge each other.** Every turn, find AT LEAST ONE thing to push back on. Unconditional agreement is forbidden. Even if you agree 90%, find the 10% to challenge.
4. **Argue with evidence.** Show code, show data, show examples. "I think" is weak. "This test proves" is strong.
5. **3-round limit** on disagreements. Then prototype both approaches and let test results decide.
6. **Keep context small.** Only read files relevant to your current task. Don't read every file every turn.
7. **Update memory.** If you discover a bug pattern, a gotcha, or something that works well, append it to MEMORY.md.
8. **Push immediately** after your turn. One commit per turn.
9. **Under 80 lines.** No filler, no repetition.
10. **User is middleware.** Only provides keys/access via USER.md.

## Testing Requirements
- Every new module needs tests
- Tests must pass before committing: `cd workspace && python -m pytest -x --tb=short`
- If you change existing code, run existing tests first to catch regressions
- The bridge runs pytest independently — if tests fail, YOUR turn continues until they pass

## Message Format
```
## Turn [N] — [Mind A (Kiran) / Mind B (Arjun)] — [timestamp]
**Phase:** PLANNING | CODING | REVIEWING | TESTING | FIX_TESTS
**Tests:** [X passed / Y failed] or [no code changes]
**Pushback:** [the one thing you disagree with or challenge]

[Your message. Be specific.]
---
```

## Memory System
- MEMORY.md = shared knowledge base
- Read it at the start of each turn
- Append to it when you learn something important
- Sections: Patterns, Mistakes Made, Technical Gotchas, What Works Well

## STATUS.json Format
```json
{
  "current_turn": "MIND_A | MIND_B",
  "phase": "PLANNING | CODING | REVIEWING | TESTING | FIX_TESTS",
  "turn_number": 0,
  "last_action": "what just happened",
  "next_expected": "what the next mind should do",
  "tests_passing": true,
  "test_count": 0,
  "user_action_needed": false,
  "project_progress": "0%"
}
```
