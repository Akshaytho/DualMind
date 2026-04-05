"""Tests for FastAPI web endpoints and dry_run_verdict logic."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rulelint.ingestion import DocumentText, PageText
from rulelint.models import Authority, Conflict, ConflictType, Rule, RuleType
from rulelint.web import app, dry_run_verdict


@pytest.fixture
def client():
    return TestClient(app)


# ── dry_run_verdict unit tests ────────────────────────────────────────────


class TestDryRunVerdict:
    def test_all_good_pages(self):
        doc = DocumentText(
            source_path="test.pdf",
            pages=[
                PageText(page_number=1, text="The building regulations require minimum setback of five meters from the road boundary", method="pdfplumber"),
                PageText(page_number=2, text="Construction permits shall be obtained from the municipal authority before commencing work", method="pdfplumber"),
            ],
        )
        v = dry_run_verdict(doc)
        assert v.overall_grade == "good"
        assert "GOOD" in v.verdict
        assert v.page_count == 2
        assert v.failed_pages == []

    def test_mixed_quality_pages(self):
        doc = DocumentText(
            source_path="test.pdf",
            pages=[
                PageText(page_number=1, text="The building regulations require minimum setback distance", method="pdfplumber"),
                PageText(page_number=2, text="| ~ ^ x 2 . # $ % & *", method="ocr"),
            ],
        )
        v = dry_run_verdict(doc)
        assert v.overall_grade == "poor"
        assert "POOR" in v.verdict
        assert v.ocr_pages == [2]

    def test_all_failed_pages(self):
        doc = DocumentText(
            source_path="test.pdf",
            pages=[
                PageText(page_number=1, text="", method="none"),
                PageText(page_number=2, text="", method="none"),
            ],
        )
        v = dry_run_verdict(doc)
        assert v.overall_grade == "poor"
        assert "FAIL" in v.verdict
        assert v.failed_pages == [1, 2]

    def test_empty_document(self):
        doc = DocumentText(source_path="test.pdf", pages=[])
        v = dry_run_verdict(doc)
        assert v.page_count == 0
        assert v.overall_grade == "poor"

    def test_fair_verdict(self):
        doc = DocumentText(
            source_path="test.pdf",
            pages=[
                PageText(page_number=1, text="The building regulations require minimum setback of five meters", method="pdfplumber"),
                PageText(page_number=2, text="Sec 4.2 BUA FAR 2.5 max MCH GHQ", method="ocr"),
            ],
        )
        v = dry_run_verdict(doc)
        assert v.overall_grade in ("fair", "poor")

    def test_verdict_page_details(self):
        doc = DocumentText(
            source_path="test.pdf",
            pages=[
                PageText(page_number=1, text="Regulation text with sufficient words for testing quality", method="pdfplumber"),
            ],
        )
        v = dry_run_verdict(doc)
        assert len(v.pages) == 1
        assert v.pages[0].page_number == 1
        assert v.pages[0].method == "pdfplumber"
        assert v.pages[0].chars > 0


# ── API endpoint tests ────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestRulesEndpoint:
    def test_list_rules_empty(self, client, tmp_path):
        db = str(tmp_path / "test.db")
        resp = client.get("/rules", params={"db": db})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["rules"] == []

    def test_list_rules_with_data(self, client, tmp_path):
        from rulelint.store import RuleStore

        db = str(tmp_path / "test.db")
        rule = Rule(
            rule_id="GHMC-BP-001", title="Setback", description="Min setback 5m",
            authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT,
            section_ref="4.1",
        )
        with RuleStore(db) as store:
            store.save_rule(rule)

        resp = client.get("/rules", params={"db": db})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["rules"][0]["rule_id"] == "GHMC-BP-001"


class TestConflictsEndpoint:
    def test_list_conflicts_empty(self, client, tmp_path):
        db = str(tmp_path / "test.db")
        resp = client.get("/conflicts", params={"db": db})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_filter_by_type(self, client, tmp_path):
        from rulelint.store import RuleStore

        db = str(tmp_path / "test.db")
        with RuleStore(db) as store:
            store.save_conflicts([
                Conflict(
                    conflict_type=ConflictType.CONTRADICTION,
                    rule_ids=["A", "B"],
                    description="test",
                    severity="high",
                ),
            ])

        resp = client.get("/conflicts", params={"db": db, "conflict_type": "contradiction"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1


class TestDetectEndpoint:
    def test_detect_no_rules(self, client, tmp_path):
        db = str(tmp_path / "test.db")
        resp = client.post("/detect", params={"db": db})
        assert resp.status_code == 404

    def test_detect_with_rules(self, client, tmp_path):
        from rulelint.store import RuleStore

        db = str(tmp_path / "test.db")
        rules = [
            Rule(
                rule_id="GHMC-BP-001", title="Setback", description="Min 5m",
                authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT,
                section_ref="4.1",
            ),
            Rule(
                rule_id="HMDA-BP-001", title="No setback", description="No setback needed",
                authority=Authority.HMDA, rule_type=RuleType.PROHIBITION,
                section_ref="3.1",
            ),
        ]
        with RuleStore(db) as store:
            store.save_rules(rules)

        resp = client.post("/detect", params={"db": db})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1


class TestDryRunEndpoint:
    def test_rejects_non_pdf(self, client):
        resp = client.post("/dry-run", files={"file": ("test.txt", b"hello", "text/plain")})
        assert resp.status_code == 400

    def test_dry_run_with_pdf(self, client):
        """Mock ingest_pdf since we don't have a real PDF in tests."""
        mock_doc = DocumentText(
            source_path="/tmp/test.pdf",
            pages=[
                PageText(page_number=1, text="Building regulation text with adequate words for quality scoring", method="pdfplumber"),
            ],
        )
        with patch("rulelint.web.ingest_pdf", return_value=mock_doc):
            resp = client.post("/dry-run", files={"file": ("test.pdf", b"%PDF-fake", "application/pdf")})

        assert resp.status_code == 200
        data = resp.json()
        assert data["page_count"] == 1
        assert "verdict" in data
        assert "overall_grade" in data


# ── POST /analyze endpoint tests ─────────────────────────────────────────


class TestAnalyzeEndpoint:
    def test_rejects_non_pdf(self, client):
        resp = client.post("/analyze", files={"file": ("test.txt", b"hello", "text/plain")})
        assert resp.status_code == 400

    def test_rejects_when_no_api_key(self, client):
        """Should 400 when no API key is configured server-side."""
        mock_doc = DocumentText(
            source_path="/tmp/test.pdf",
            pages=[
                PageText(page_number=1, text="Building regulation text with adequate words", method="pdfplumber"),
            ],
        )
        with patch("rulelint.web.ingest_pdf", return_value=mock_doc), \
             patch.dict("os.environ", {}, clear=True), \
             patch("rulelint.web._get_api_key", return_value=None):
            resp = client.post("/analyze", files={"file": ("test.pdf", b"%PDF-fake", "application/pdf")})
        assert resp.status_code == 400
        assert "API key" in resp.json()["detail"]

    def test_analyze_full_pipeline(self, client, tmp_path):
        """Mock ingest + extract to test full pipeline through the endpoint."""
        mock_doc = DocumentText(
            source_path="/tmp/test.pdf",
            pages=[
                PageText(page_number=1, text="Building regulation text with adequate words", method="pdfplumber"),
            ],
        )
        mock_rules = [
            Rule(
                rule_id="GHMC-BP-001", title="Setback", description="Min 5m setback",
                authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT,
                section_ref="4.1",
            ),
            Rule(
                rule_id="HMDA-BP-001", title="No setback", description="No setback needed",
                authority=Authority.HMDA, rule_type=RuleType.PROHIBITION,
                section_ref="3.1",
            ),
        ]
        db = str(tmp_path / "test.db")
        with patch("rulelint.web.ingest_pdf", return_value=mock_doc), \
             patch("rulelint.web.extract_rules", return_value=mock_rules), \
             patch("rulelint.web._get_api_key", return_value="fake-key"):
            resp = client.post(
                "/analyze",
                files={"file": ("test.pdf", b"%PDF-fake", "application/pdf")},
                params={"db": db},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["rules_count"] == 2
        assert data["conflicts_count"] >= 1  # contradiction detected
        assert len(data["rules"]) == 2
        assert len(data["conflicts"]) >= 1

    def test_analyze_with_authority_hint(self, client, tmp_path):
        """Authority hint should be passed through to extract_rules."""
        mock_doc = DocumentText(
            source_path="/tmp/test.pdf",
            pages=[
                PageText(page_number=1, text="Regulation text for authority test", method="pdfplumber"),
            ],
        )
        mock_rules = [
            Rule(
                rule_id="GHMC-BP-001", title="Test", description="Test rule",
                authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT,
                section_ref="1.0",
            ),
        ]
        db = str(tmp_path / "test.db")
        with patch("rulelint.web.ingest_pdf", return_value=mock_doc), \
             patch("rulelint.web.extract_rules", return_value=mock_rules) as mock_extract, \
             patch("rulelint.web._get_api_key", return_value="fake-key"):
            resp = client.post(
                "/analyze",
                files={"file": ("test.pdf", b"%PDF-fake", "application/pdf")},
                params={"db": db, "authority": "ghmc"},
            )

        assert resp.status_code == 200
        # Verify authority_hint was passed to extract_rules
        mock_extract.assert_called_once()
        call_kwargs = mock_extract.call_args
        assert call_kwargs[1].get("authority_hint") == "ghmc" or \
               (len(call_kwargs[0]) > 1 and call_kwargs[0][1] == "ghmc")

    def test_analyze_extraction_failure(self, client):
        """Should 500 when extraction fails."""
        from rulelint.extraction import ExtractionError

        mock_doc = DocumentText(
            source_path="/tmp/test.pdf",
            pages=[
                PageText(page_number=1, text="Some text here for testing", method="pdfplumber"),
            ],
        )
        with patch("rulelint.web.ingest_pdf", return_value=mock_doc), \
             patch("rulelint.web.extract_rules", side_effect=ExtractionError("LLM error")), \
             patch("rulelint.web._get_api_key", return_value="fake-key"):
            resp = client.post("/analyze", files={"file": ("test.pdf", b"%PDF-fake", "application/pdf")})
        assert resp.status_code == 502
        assert "extraction" in resp.json()["detail"].lower() or "LLM" in resp.json()["detail"]

    def test_analyze_empty_pdf(self, client):
        """Should 422 when PDF has no extractable text."""
        mock_doc = DocumentText(source_path="/tmp/test.pdf", pages=[])
        with patch("rulelint.web.ingest_pdf", return_value=mock_doc), \
             patch("rulelint.web._get_api_key", return_value="fake-key"):
            resp = client.post("/analyze", files={"file": ("test.pdf", b"%PDF-fake", "application/pdf")})
        assert resp.status_code == 422
        assert "no text" in resp.json()["detail"].lower() or "empty" in resp.json()["detail"].lower()
