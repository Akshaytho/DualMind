# Shared Memory

Things both minds have learned. Read this every turn. Append when you discover something important.

## Patterns
_None yet._

## Mistakes Made
_None yet._

## Technical Gotchas
- `RuleStore` needs context manager usage (`with` statement) — raw `.close()` calls leak on exceptions

## What Works Well
- All modules follow single-entry-point pattern: `ingest_pdf()`, `extract_rules()`, `detect_conflicts()`, `RuleStore`, `main()`
- 116 tests, all mocked where needed (no API key, no real PDFs)
