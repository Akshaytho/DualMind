"""FastAPI web UI — thin layer over the same pipeline as CLI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel

from .detection import detect_conflicts
from .extraction import ExtractionError, extract_rules
from .ingestion import DocumentText, ingest_pdf, text_quality
from .models import Conflict, ConflictType, Rule
from .store import RuleStore

DEFAULT_DB = "rulelint.db"

app = FastAPI(title="RuleLint", description="Regulation conflict detector for Indian cities")


# ── Response models ───────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"


class PageQuality(BaseModel):
    page_number: int
    chars: int
    method: str
    grade: str
    alpha_ratio: float
    avg_word_length: float


class DryRunVerdict(BaseModel):
    page_count: int
    total_chars: int
    pages: list[PageQuality]
    overall_grade: str
    verdict: str
    ocr_pages: list[int]
    failed_pages: list[int]


class AnalyzeResponse(BaseModel):
    rules_count: int
    conflicts_count: int
    rules: list[Rule]
    conflicts: list[Conflict]


class RulesResponse(BaseModel):
    count: int
    rules: list[Rule]


class ConflictsResponse(BaseModel):
    count: int
    conflicts: list[Conflict]


# ── Verdict logic ─────────────────────────────────────────────────────────


def dry_run_verdict(doc: DocumentText) -> DryRunVerdict:
    """Aggregate per-page quality into an overall go/no-go verdict."""
    pages: list[PageQuality] = []
    ocr_pages: list[int] = []
    failed_pages: list[int] = []
    total_chars = 0
    grades: list[str] = []

    for p in doc.pages:
        chars = len(p.text)
        total_chars += chars

        if p.method == "none":
            failed_pages.append(p.page_number)
            pages.append(PageQuality(
                page_number=p.page_number, chars=0, method="none",
                grade="failed", alpha_ratio=0.0, avg_word_length=0.0,
            ))
            grades.append("failed")
        elif chars == 0:
            pages.append(PageQuality(
                page_number=p.page_number, chars=0, method=p.method,
                grade="empty", alpha_ratio=0.0, avg_word_length=0.0,
            ))
            grades.append("empty")
        else:
            q = text_quality(p.text)
            pages.append(PageQuality(
                page_number=p.page_number, chars=chars, method=p.method,
                grade=q["grade"], alpha_ratio=q["alpha_ratio"],
                avg_word_length=q["avg_word_length"],
            ))
            grades.append(q["grade"])

        if p.method == "ocr":
            ocr_pages.append(p.page_number)

    # Overall grade: worst grade across all pages with extractable text
    # (skip empty/failed for grading, but if ALL failed → poor)
    text_grades = [g for g in grades if g not in ("failed", "empty")]
    if not text_grades:
        overall = "poor"
    elif any(g == "poor" for g in text_grades):
        overall = "poor"
    elif any(g == "fair" for g in text_grades):
        overall = "fair"
    else:
        overall = "good"

    # Verdict message
    if failed_pages and len(failed_pages) == doc.page_count:
        verdict = "FAIL — no text could be extracted from any page"
    elif overall == "poor":
        verdict = "POOR — extraction may produce unreliable results, review manually"
    elif overall == "fair":
        verdict = "FAIR — extraction should work but review low-quality pages"
    else:
        verdict = "GOOD — safe to proceed with extraction"

    return DryRunVerdict(
        page_count=doc.page_count,
        total_chars=total_chars,
        pages=pages,
        overall_grade=overall,
        verdict=verdict,
        ocr_pages=ocr_pages,
        failed_pages=failed_pages,
    )


# ── Helpers ───────────────────────────────────────────────────────────────


def _get_api_key() -> str | None:
    """Get API key from server-side config (env var). Never from request body."""
    return os.environ.get("ANTHROPIC_API_KEY")


# ── Endpoints ─────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/dry-run", response_model=DryRunVerdict)
async def dry_run(file: UploadFile) -> DryRunVerdict:
    """Upload a PDF, get ingestion quality stats without calling Claude API."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        doc = ingest_pdf(tmp_path)
        return dry_run_verdict(doc)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/rules", response_model=RulesResponse)
def list_rules(db: str = DEFAULT_DB) -> RulesResponse:
    """List all stored rules."""
    with RuleStore(db) as store:
        rules = store.get_all_rules()
    return RulesResponse(count=len(rules), rules=rules)


@app.get("/conflicts", response_model=ConflictsResponse)
def list_conflicts(db: str = DEFAULT_DB, conflict_type: str | None = None) -> ConflictsResponse:
    """List detected conflicts, optionally filtered by type."""
    ct = ConflictType(conflict_type) if conflict_type else None
    with RuleStore(db) as store:
        conflicts = store.get_conflicts(ct)
    return ConflictsResponse(count=len(conflicts), conflicts=conflicts)


@app.post("/detect", response_model=ConflictsResponse)
def run_detection(db: str = DEFAULT_DB) -> ConflictsResponse:
    """Re-run conflict detection on all stored rules."""
    with RuleStore(db) as store:
        rules = store.get_all_rules()
        if not rules:
            raise HTTPException(status_code=404, detail="No rules in database. Run analyze first.")
        conflicts = detect_conflicts(rules)
        store.save_conflicts(conflicts)
    return ConflictsResponse(count=len(conflicts), conflicts=conflicts)


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    file: UploadFile,
    authority: str | None = None,
    db: str = DEFAULT_DB,
) -> AnalyzeResponse:
    """Full pipeline: upload PDF → ingest → extract rules → detect conflicts.

    API key is read from server-side ANTHROPIC_API_KEY env var (never from request).
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="API key not configured. Set ANTHROPIC_API_KEY on the server.",
        )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Step 1: Ingest
        doc = ingest_pdf(tmp_path)
        if not doc.pages or not doc.full_text.strip():
            raise HTTPException(status_code=422, detail="No text extracted from PDF — empty or unreadable")

        # Step 2: Extract rules via Claude API
        try:
            rules = extract_rules(
                doc.full_text,
                authority_hint=authority,
                api_key=api_key,
            )
        except ExtractionError as exc:
            raise HTTPException(status_code=502, detail=f"Extraction failed: {exc}")

        # Step 3: Store + detect conflicts
        with RuleStore(db) as store:
            store.save_rules(rules, source_file=file.filename or "upload.pdf")
            all_rules = store.get_all_rules()
            conflicts = detect_conflicts(all_rules)
            store.save_conflicts(conflicts)

        return AnalyzeResponse(
            rules_count=len(rules),
            conflicts_count=len(conflicts),
            rules=rules,
            conflicts=conflicts,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
