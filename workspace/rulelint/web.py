"""FastAPI web UI — thin layer over the same pipeline as CLI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
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


def _safe_db(db: str) -> str:
    """Sanitise the db parameter to prevent path traversal.

    Only bare filenames ending in .db are allowed. Anything with path
    separators or non-.db suffixes is rejected.
    """
    name = Path(db).name  # strip any directory components
    if name != db or not name.endswith(".db"):
        raise HTTPException(status_code=400, detail="Invalid database name — use a plain .db filename")
    return name


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
    db = _safe_db(db)
    with RuleStore(db) as store:
        rules = store.get_all_rules()
    return RulesResponse(count=len(rules), rules=rules)


@app.get("/conflicts", response_model=ConflictsResponse)
def list_conflicts(db: str = DEFAULT_DB, conflict_type: str | None = None) -> ConflictsResponse:
    """List detected conflicts, optionally filtered by type."""
    db = _safe_db(db)
    ct = ConflictType(conflict_type) if conflict_type else None
    with RuleStore(db) as store:
        conflicts = store.get_conflicts(ct)
    return ConflictsResponse(count=len(conflicts), conflicts=conflicts)


@app.post("/detect", response_model=ConflictsResponse)
def run_detection(db: str = DEFAULT_DB) -> ConflictsResponse:
    """Re-run conflict detection on all stored rules."""
    db = _safe_db(db)
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
    db = _safe_db(db)

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


# ── HTML Frontend ─────────────────────────────────────────────────────────

_INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RuleLint — Regulation Conflict Detector</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;max-width:860px;margin:0 auto;padding:1.5rem;color:#1a1a1a;background:#fafafa}
h1{font-size:1.5rem;margin-bottom:.25rem}
.subtitle{color:#666;margin-bottom:1.5rem;font-size:.9rem}
.card{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:1.25rem;margin-bottom:1rem}
h2{font-size:1.1rem;margin-bottom:.75rem}
label{font-weight:600;display:block;margin-bottom:.25rem;font-size:.9rem}
input[type=file]{margin-bottom:.75rem}
select,input[type=text]{padding:.4rem .6rem;border:1px solid #ccc;border-radius:4px;font-size:.9rem;margin-bottom:.75rem;width:100%}
button{background:#2563eb;color:#fff;border:none;padding:.5rem 1.2rem;border-radius:4px;cursor:pointer;font-size:.9rem}
button:hover{background:#1d4ed8}
button:disabled{background:#94a3b8;cursor:not-allowed}
#status{margin-top:.75rem;padding:.5rem;border-radius:4px;font-size:.85rem;display:none}
.ok{background:#dcfce7;color:#166534;display:block}
.err{background:#fee2e2;color:#991b1b;display:block}
.info{background:#dbeafe;color:#1e40af;display:block}
table{width:100%;border-collapse:collapse;font-size:.85rem;margin-top:.5rem}
th,td{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #e5e7eb}
th{background:#f1f5f9;font-weight:600}
.severity-high{color:#dc2626;font-weight:600}
.severity-medium{color:#d97706}
.severity-low{color:#059669}
.hidden{display:none}
.tabs{display:flex;gap:.5rem;margin-bottom:.75rem}
.tab{padding:.35rem .8rem;border:1px solid #ccc;border-radius:4px;background:#fff;cursor:pointer;font-size:.85rem}
.tab.active{background:#2563eb;color:#fff;border-color:#2563eb}
#results{margin-top:1rem}
</style>
</head>
<body>
<h1>RuleLint</h1>
<p class="subtitle">Upload a municipal PDF to extract rules and detect conflicts</p>

<div class="card">
<h2>Upload &amp; Analyze</h2>
<form id="form">
  <label for="pdf">PDF document</label>
  <input type="file" id="pdf" accept=".pdf" required>
  <label for="mode">Action</label>
  <select id="mode">
    <option value="dry-run">Dry run (check quality only)</option>
    <option value="analyze">Full analysis (requires API key on server)</option>
  </select>
  <div id="authority-row" class="hidden">
    <label for="authority">Authority hint (optional)</label>
    <input type="text" id="authority" placeholder="e.g. ghmc, hmda">
  </div>
  <button type="submit" id="btn">Upload</button>
</form>
<div id="status"></div>
</div>

<div id="results" class="hidden">
<div class="card">
  <div class="tabs">
    <span class="tab active" data-tab="rules">Rules</span>
    <span class="tab" data-tab="conflicts">Conflicts</span>
    <span class="tab" data-tab="quality">Quality</span>
  </div>
  <div id="tab-rules"></div>
  <div id="tab-conflicts" class="hidden"></div>
  <div id="tab-quality" class="hidden"></div>
</div>
</div>

<script>
const form=document.getElementById('form'),pdf=document.getElementById('pdf'),
  mode=document.getElementById('mode'),btn=document.getElementById('btn'),
  status=document.getElementById('status'),results=document.getElementById('results'),
  authRow=document.getElementById('authority-row'),authInput=document.getElementById('authority');

mode.addEventListener('change',()=>{authRow.classList.toggle('hidden',mode.value!=='analyze')});

document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  ['rules','conflicts','quality'].forEach(id=>{
    document.getElementById('tab-'+id).classList.toggle('hidden',id!==t.dataset.tab);
  });
}));

function setStatus(msg,cls){status.className=cls;status.textContent=msg;status.style.display='block'}

form.addEventListener('submit',async e=>{
  e.preventDefault();
  if(!pdf.files.length)return;
  btn.disabled=true;
  setStatus('Uploading...','info');
  results.classList.add('hidden');
  const fd=new FormData();
  fd.append('file',pdf.files[0]);
  let url='/'+mode.value;
  if(mode.value==='analyze'&&authInput.value)url+='?authority='+encodeURIComponent(authInput.value);
  try{
    const r=await fetch(url,{method:'POST',body:fd});
    const d=await r.json();
    if(!r.ok){setStatus('Error: '+(d.detail||r.statusText),'err');return}
    if(mode.value==='dry-run')showDryRun(d);
    else showAnalysis(d);
    results.classList.remove('hidden');
    setStatus(mode.value==='dry-run'?'Quality check complete: '+d.verdict:'Analysis complete: '+d.rules_count+' rules, '+d.conflicts_count+' conflicts','ok');
  }catch(err){setStatus('Network error: '+err.message,'err')}
  finally{btn.disabled=false}
});

function showDryRun(d){
  document.getElementById('tab-rules').innerHTML='<p>Run full analysis to see rules.</p>';
  document.getElementById('tab-conflicts').innerHTML='<p>Run full analysis to see conflicts.</p>';
  let h='<table><tr><th>Page</th><th>Method</th><th>Chars</th><th>Grade</th><th>Alpha</th><th>Avg Word</th></tr>';
  (d.pages||[]).forEach(p=>{h+='<tr><td>'+p.page_number+'</td><td>'+p.method+'</td><td>'+p.chars+'</td><td>'+p.grade+'</td><td>'+p.alpha_ratio.toFixed(2)+'</td><td>'+p.avg_word_length.toFixed(1)+'</td></tr>'});
  h+='</table>';
  document.getElementById('tab-quality').innerHTML=h;
  document.querySelectorAll('.tab').forEach(t=>{t.classList.toggle('active',t.dataset.tab==='quality')});
  ['rules','conflicts','quality'].forEach(id=>{document.getElementById('tab-'+id).classList.toggle('hidden',id!=='quality')});
}

function showAnalysis(d){
  let h='<table><tr><th>ID</th><th>Title</th><th>Authority</th><th>Type</th><th>Section</th></tr>';
  (d.rules||[]).forEach(r=>{h+='<tr><td>'+r.rule_id+'</td><td>'+esc(r.title)+'</td><td>'+r.authority+'</td><td>'+r.rule_type+'</td><td>'+(r.section_ref||'&#8212;')+'</td></tr>'});
  h+='</table>';
  document.getElementById('tab-rules').innerHTML=h;

  let c='<table><tr><th>Type</th><th>Rules</th><th>Severity</th><th>Description</th></tr>';
  (d.conflicts||[]).forEach(x=>{c+='<tr><td>'+x.conflict_type+'</td><td>'+x.rule_ids.join(', ')+'</td><td><span class="severity-'+x.severity+'">'+x.severity+'</span></td><td>'+esc(x.description)+'</td></tr>'});
  c+='</table>';
  document.getElementById('tab-conflicts').innerHTML=c;
  document.getElementById('tab-quality').innerHTML='<p>Use dry-run mode for quality details.</p>';
}

function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Serve the single-page HTML frontend."""
    return _INDEX_HTML
