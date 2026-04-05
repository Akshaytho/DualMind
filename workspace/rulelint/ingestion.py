"""PDF → clean text ingestion. Layer 1 of the 3-layer architecture."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


@dataclass
class PageText:
    """Extracted text from a single PDF page."""

    page_number: int
    text: str
    method: str = "pdfplumber"  # "pdfplumber" or "ocr"


@dataclass
class DocumentText:
    """Extracted text from an entire PDF document."""

    source_path: str
    pages: list[PageText] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def ingest_pdf(path: str | Path) -> DocumentText:
    """Extract text from a PDF file. Single entry point for ingestion layer.

    Uses pdfplumber for native text extraction. Falls back to OCR (Tesseract)
    for pages where pdfplumber returns no usable text.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if not path.suffix.lower() == ".pdf":
        raise ValueError(f"Not a PDF file: {path}")

    doc = DocumentText(source_path=str(path))

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            raw = page.extract_text() or ""
            cleaned = _clean_text(raw)

            if _is_usable(cleaned):
                doc.pages.append(PageText(page_number=i, text=cleaned, method="pdfplumber"))
            else:
                # OCR fallback — only attempt if pytesseract is available
                ocr_text = _ocr_page(page)
                if ocr_text:
                    doc.pages.append(PageText(page_number=i, text=ocr_text, method="ocr"))
                else:
                    doc.pages.append(PageText(page_number=i, text="", method="none"))

    return doc


def _clean_text(text: str) -> str:
    """Normalize whitespace, fix common PDF extraction artifacts."""
    # Collapse multiple spaces/tabs to single space
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split("\n")]
    # Remove empty leading/trailing lines
    text = "\n".join(lines).strip()
    return text


def _is_usable(text: str) -> bool:
    """Check if extracted text has enough content to be useful."""
    # At least 20 non-whitespace characters
    return len(re.sub(r"\s", "", text)) >= 20


def _ocr_page(page: pdfplumber.page.Page) -> str:
    """Attempt OCR on a page image. Returns empty string if Tesseract unavailable."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    try:
        img = page.to_image(resolution=300).original
        raw = pytesseract.image_to_string(img)
        return _clean_text(raw)
    except Exception:
        return ""
