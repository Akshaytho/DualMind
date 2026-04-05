"""CLI entry point — glues ingestion, extraction, detection, and store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .detection import detect_conflicts
from .extraction import ExtractionError, extract_rules
from .ingestion import ingest_pdf, text_quality
from .models import ConflictType
from .store import RuleStore
from .web import dry_run_verdict

DEFAULT_DB = "rulelint.db"


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, 1 on error."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rulelint",
        description="Regulation conflict detector for Indian cities",
    )
    sub = parser.add_subparsers(title="commands")

    # ── analyze: full pipeline ───────────────────────────────────────────
    p_analyze = sub.add_parser("analyze", help="Ingest PDF, extract rules, detect conflicts")
    p_analyze.add_argument("pdf", type=Path, help="Path to PDF file")
    p_analyze.add_argument("--authority", choices=["ghmc", "hmda"], help="Authority hint for extraction")
    p_analyze.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    p_analyze.add_argument("--api-key", dest="api_key", help="Anthropic API key (or set ANTHROPIC_API_KEY)")
    p_analyze.add_argument("--dry-run", dest="dry_run", action="store_true", default=False, help="Ingest only — show text quality stats, skip extraction (no API credits used)")
    p_analyze.set_defaults(func=_cmd_analyze)

    # ── detect: run detection on stored rules ────────────────────────────
    p_detect = sub.add_parser("detect", help="Run conflict detection on stored rules")
    p_detect.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    p_detect.set_defaults(func=_cmd_detect)

    # ── rules: list stored rules ─────────────────────────────────────────
    p_rules = sub.add_parser("rules", help="List stored rules")
    p_rules.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    p_rules.set_defaults(func=_cmd_rules)

    # ── conflicts: list detected conflicts ───────────────────────────────
    p_conflicts = sub.add_parser("conflicts", help="List detected conflicts")
    p_conflicts.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    p_conflicts.add_argument(
        "--type",
        dest="conflict_type",
        choices=[ct.value for ct in ConflictType],
        help="Filter by conflict type",
    )
    p_conflicts.set_defaults(func=_cmd_conflicts)

    return parser


# ── Command implementations ──────────────────────────────────────────────


def _cmd_analyze(args: argparse.Namespace) -> int:
    """Full pipeline: PDF → text → rules → conflicts → store."""
    pdf_path: Path = args.pdf

    # Step 1: Ingest
    print(f"Ingesting {pdf_path}...")
    doc = ingest_pdf(pdf_path)
    if not doc.pages:
        print("No usable text extracted from PDF.", file=sys.stderr)
        return 1
    print(f"  {doc.page_count} pages, {len(doc.full_text)} chars extracted")

    # Dry run: show ingestion quality stats and exit (no API call)
    if args.dry_run:
        _print_ingestion_report(doc)
        return 0

    # Step 2: Extract
    print("Extracting rules via Claude API...")
    try:
        rules = extract_rules(
            doc.full_text,
            authority_hint=args.authority,
            api_key=args.api_key,
        )
    except ExtractionError as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1
    print(f"  {len(rules)} rules extracted")

    # Step 3: Store rules
    with RuleStore(args.db) as store:
        store.save_rules(rules, source_file=str(pdf_path))
        print(f"  Saved to {args.db}")

        # Step 4: Detect conflicts (on ALL stored rules, not just this batch)
        all_rules = store.get_all_rules()
        conflicts = detect_conflicts(all_rules)
        store.save_conflicts(conflicts)

        # Step 5: Report
        _print_summary(rules, conflicts)
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    """Run detection on stored rules."""
    with RuleStore(args.db) as store:
        rules = store.get_all_rules()
        if not rules:
            print("No rules in database. Run 'analyze' first.")
            return 1

        conflicts = detect_conflicts(rules)
        store.save_conflicts(conflicts)
        _print_summary(rules, conflicts)
    return 0


def _cmd_rules(args: argparse.Namespace) -> int:
    """List stored rules."""
    with RuleStore(args.db) as store:
        rules = store.get_all_rules()
        if not rules:
            print("No rules in database.")
            return 0

        low_conf = []
        for r in rules:
            status_tag = f" [{r.status}]" if r.status != "active" else ""
            conf_tag = f" (conf={r.confidence:.0%})" if r.confidence < 0.85 else ""
            print(f"  {r.rule_id}  {r.authority}/{r.rule_type}{status_tag}{conf_tag}  {r.title}")
            if r.confidence < 0.85:
                low_conf.append(r.rule_id)
        print(f"\n{len(rules)} rules total")
        if low_conf:
            print(f"  {len(low_conf)} below 85% confidence — manual review recommended (D5)")
    return 0


def _cmd_conflicts(args: argparse.Namespace) -> int:
    """List detected conflicts."""
    with RuleStore(args.db) as store:
        ct = ConflictType(args.conflict_type) if args.conflict_type else None
        conflicts = store.get_conflicts(ct)

        if not conflicts:
            label = f" ({ct.value})" if ct else ""
            print(f"No conflicts{label} found.")
            return 0

        for c in conflicts:
            severity = c.severity.upper()
            print(f"  [{severity}] {c.conflict_type}: {c.description}")
        print(f"\n{len(conflicts)} conflicts total")
    return 0


def _print_ingestion_report(doc) -> None:
    """Print per-page text quality stats for --dry-run."""
    ocr_pages = []
    empty_pages = []
    failed_pages = []
    total_chars = 0

    for p in doc.pages:
        chars = len(p.text)
        total_chars += chars

        if p.method == "none":
            failed_pages.append(p.page_number)
            print(f"  Page {p.page_number}: FAILED [no text extracted]")
        elif chars == 0:
            empty_pages.append(p.page_number)
            print(f"  Page {p.page_number}: EMPTY [{p.method}]")
        else:
            q = text_quality(p.text)
            grade_tag = q["grade"].upper()
            print(f"  Page {p.page_number}: {chars} chars [{p.method}] quality={grade_tag} (alpha={q['alpha_ratio']:.0%}, avgword={q['avg_word_length']})")

        if p.method == "ocr":
            ocr_pages.append(p.page_number)

    print(f"\nTotal: {doc.page_count} pages, {total_chars} chars")
    if ocr_pages:
        print(f"  OCR fallback on {len(ocr_pages)} page(s): {ocr_pages}")
    if failed_pages:
        print(f"  Extraction failed on {len(failed_pages)} page(s): {failed_pages}")
    if empty_pages:
        print(f"  Empty pages: {empty_pages}")

    v = dry_run_verdict(doc)
    print(f"\nVerdict: {v.verdict}")
    print("Dry run complete — no API credits used.")


def _print_summary(rules: list, conflicts: list) -> None:
    """Print a brief summary of analysis results."""
    print(f"\n{'='*60}")
    print(f"Rules: {len(rules)}  |  Conflicts: {len(conflicts)}")
    if conflicts:
        by_type: dict[str, int] = {}
        for c in conflicts:
            by_type[c.conflict_type] = by_type.get(c.conflict_type, 0) + 1
        for ct, count in sorted(by_type.items()):
            print(f"  {ct}: {count}")
    print(f"{'='*60}")


if __name__ == "__main__":
    sys.exit(main())
