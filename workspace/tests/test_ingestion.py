"""Tests for ingestion.py — PDF text extraction."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rulelint.ingestion import DocumentText, PageText, _clean_text, _is_usable, ingest_pdf, text_quality


# ── Unit tests for text cleaning ───────────────────────────────────────────


class TestCleanText:
    def test_collapses_spaces(self):
        assert _clean_text("hello   world") == "hello world"

    def test_collapses_tabs(self):
        assert _clean_text("hello\t\tworld") == "hello world"

    def test_collapses_excessive_newlines(self):
        result = _clean_text("a\n\n\n\nb")
        assert result == "a\n\nb"

    def test_strips_line_whitespace(self):
        result = _clean_text("  hello  \n  world  ")
        assert result == "hello\nworld"

    def test_empty_string(self):
        assert _clean_text("") == ""


class TestIsUsable:
    def test_usable_text(self):
        assert _is_usable("This is a regulation about building permits") is True

    def test_too_short(self):
        assert _is_usable("Hi") is False

    def test_whitespace_only(self):
        assert _is_usable("   \n\n   ") is False

    def test_exactly_threshold(self):
        # 20 non-whitespace chars
        assert _is_usable("a" * 20) is True
        assert _is_usable("a" * 19) is False


# ── DocumentText model ─────────────────────────────────────────────────────


class TestDocumentText:
    def test_full_text(self):
        doc = DocumentText(
            source_path="test.pdf",
            pages=[
                PageText(page_number=1, text="Page one content"),
                PageText(page_number=2, text="Page two content"),
            ],
        )
        assert "Page one content" in doc.full_text
        assert "Page two content" in doc.full_text

    def test_page_count(self):
        doc = DocumentText(
            source_path="test.pdf",
            pages=[PageText(page_number=i, text=f"Page {i}") for i in range(1, 4)],
        )
        assert doc.page_count == 3

    def test_empty_pages_skipped_in_full_text(self):
        doc = DocumentText(
            source_path="test.pdf",
            pages=[
                PageText(page_number=1, text="Content"),
                PageText(page_number=2, text=""),
                PageText(page_number=3, text="More content"),
            ],
        )
        assert doc.full_text == "Content\n\nMore content"


# ── ingest_pdf function ────────────────────────────────────────────────────


class TestIngestPdf:
    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ingest_pdf("/nonexistent/file.pdf")

    def test_not_a_pdf(self, tmp_path):
        txt = tmp_path / "test.txt"
        txt.write_text("not a pdf")
        with pytest.raises(ValueError, match="Not a PDF"):
            ingest_pdf(txt)

    @patch("rulelint.ingestion.pdfplumber")
    def test_extracts_text_from_pages(self, mock_pdfplumber, tmp_path):
        """Mock pdfplumber to test the extraction pipeline."""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Section 4.2.1: Maximum building height in residential zones shall not exceed 10 meters."

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        doc = ingest_pdf(pdf_path)
        assert doc.page_count == 1
        assert "10 meters" in doc.full_text
        assert doc.pages[0].method == "pdfplumber"

# ── text_quality scoring ──────────────────────────────────────────────────


class TestTextQuality:
    def test_clean_regulation_text_scores_high(self):
        text = "The maximum building height in residential zones shall not exceed 10 meters from ground level."
        q = text_quality(text)
        assert q["avg_word_length"] > 3.0
        assert q["alpha_ratio"] > 0.7
        assert q["grade"] == "good"

    def test_ocr_garbage_scores_low(self):
        text = "| ~ ^ x | 2 . ; | ~ 1 | ; @ # $ % & * ( ) _ | | |"
        q = text_quality(text)
        assert q["alpha_ratio"] < 0.5
        assert q["grade"] == "poor"

    def test_mixed_quality_is_fair(self):
        # Real-ish text with some noise
        text = "Section 4.2 th bldg ht 10m |||  ~~ ## setback 3m fr rd"
        q = text_quality(text)
        assert q["grade"] in ("fair", "poor")

    def test_empty_text(self):
        q = text_quality("")
        assert q["grade"] == "poor"
        assert q["avg_word_length"] == 0.0
        assert q["alpha_ratio"] == 0.0

    def test_returns_expected_keys(self):
        q = text_quality("Building code section five point one")
        assert "avg_word_length" in q
        assert "alpha_ratio" in q
        assert "grade" in q


class TestIngestPdfOcrFallback:
    @patch("rulelint.ingestion.pdfplumber")
    def test_empty_page_triggers_ocr_fallback(self, mock_pdfplumber, tmp_path):
        """When pdfplumber returns empty text, OCR should be attempted."""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        # OCR won't be available in test env, so page should be empty
        doc = ingest_pdf(pdf_path)
        assert doc.page_count == 1
        assert doc.pages[0].text == ""
        assert doc.pages[0].method == "none"  # both pdfplumber and OCR failed
