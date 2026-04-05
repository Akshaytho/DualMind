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
- 121 tests, all mocked where needed (no API key, no real PDFs)
- E2E tests mock at external boundaries (pdfplumber, anthropic), not internal layers — catches interface mismatches between modules
- Scenario data in `test_e2e.py` triggers all 5 conflict types: contradiction, circular_dependency, dead_rule, jurisdictional_overlap, supersession_chain
- Package is installable: `[project.scripts]` entry point + `__main__.py` + public `__init__.py` exports
- MVP declared complete at Turn 8 (123 tests). Post-MVP: FastAPI UI, real PDF testing, OCR benchmarks
- `--dry-run` flag on `analyze` shows ingestion quality stats without calling Claude API — use before real PDF testing
