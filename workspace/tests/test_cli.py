"""Tests for cli.py — all mocked, no API key or PDF files needed."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rulelint.cli import main, _build_parser, _print_summary
from rulelint.models import Authority, Conflict, ConflictType, Rule, RuleStatus, RuleType
from rulelint.store import RuleStore


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def sample_rules():
    return [
        Rule(
            rule_id="GHMC-BP-001",
            title="Setback requirement",
            description="Minimum 3m setback from road",
            authority=Authority.GHMC,
            rule_type=RuleType.REQUIREMENT,
            status=RuleStatus.ACTIVE,
            section_ref="Sec 5.1",
        ),
        Rule(
            rule_id="HMDA-BP-001",
            title="Setback prohibition",
            description="No construction within 5m of road",
            authority=Authority.HMDA,
            rule_type=RuleType.PROHIBITION,
            status=RuleStatus.ACTIVE,
            section_ref="Sec 3.2",
        ),
    ]


@pytest.fixture
def db_with_rules(sample_rules, tmp_path):
    db_path = tmp_path / "test.db"
    store = RuleStore(db_path)
    store.save_rules(sample_rules)
    store.close()
    return str(db_path)


# ── Parser tests ─────────────────────────────────────────────────────────


class TestParser:
    def test_no_subcommand_returns_1(self, capsys):
        result = main([])
        assert result == 1

    def test_analyze_parses_pdf_path(self):
        parser = _build_parser()
        args = parser.parse_args(["analyze", "test.pdf"])
        assert args.pdf == Path("test.pdf")

    def test_analyze_with_authority(self):
        parser = _build_parser()
        args = parser.parse_args(["analyze", "test.pdf", "--authority", "ghmc"])
        assert args.authority == "ghmc"

    def test_analyze_with_db(self):
        parser = _build_parser()
        args = parser.parse_args(["analyze", "test.pdf", "--db", "custom.db"])
        assert args.db == "custom.db"

    def test_detect_default_db(self):
        parser = _build_parser()
        args = parser.parse_args(["detect"])
        assert args.db == "rulelint.db"

    def test_conflicts_with_type_filter(self):
        parser = _build_parser()
        args = parser.parse_args(["conflicts", "--type", "contradiction"])
        assert args.conflict_type == "contradiction"


# ── detect command ───────────────────────────────────────────────────────


class TestDetectCommand:
    def test_detect_no_rules(self, tmp_path):
        db_path = tmp_path / "empty.db"
        result = main(["detect", "--db", str(db_path)])
        assert result == 1

    def test_detect_with_rules(self, db_with_rules, capsys):
        result = main(["detect", "--db", db_with_rules])
        assert result == 0
        output = capsys.readouterr().out
        assert "Conflicts:" in output

    def test_detect_finds_contradiction(self, db_with_rules, capsys):
        result = main(["detect", "--db", db_with_rules])
        assert result == 0
        output = capsys.readouterr().out
        assert "contradiction" in output


# ── rules command ────────────────────────────────────────────────────────


class TestRulesCommand:
    def test_rules_empty_db(self, tmp_path, capsys):
        db_path = tmp_path / "empty.db"
        result = main(["rules", "--db", str(db_path)])
        assert result == 0
        assert "No rules" in capsys.readouterr().out

    def test_rules_lists_stored(self, db_with_rules, capsys):
        result = main(["rules", "--db", db_with_rules])
        assert result == 0
        output = capsys.readouterr().out
        assert "GHMC-BP-001" in output
        assert "HMDA-BP-001" in output
        assert "2 rules total" in output

    def test_rules_flags_low_confidence(self, tmp_path, capsys):
        db_path = tmp_path / "lowconf.db"
        store = RuleStore(db_path)
        store.save_rules([
            Rule(
                rule_id="GHMC-BP-099",
                title="Ambiguous setback",
                description="Unclear setback rule",
                authority=Authority.GHMC,
                rule_type=RuleType.REQUIREMENT,
                section_ref="S99",
                confidence=0.6,
            ),
        ])
        store.close()

        result = main(["rules", "--db", str(db_path)])
        assert result == 0
        output = capsys.readouterr().out
        assert "conf=60%" in output
        assert "manual review" in output


# ── conflicts command ────────────────────────────────────────────────────


class TestConflictsCommand:
    def test_conflicts_empty(self, tmp_path, capsys):
        db_path = tmp_path / "empty.db"
        result = main(["conflicts", "--db", str(db_path)])
        assert result == 0
        assert "No conflicts" in capsys.readouterr().out

    def test_conflicts_after_detect(self, db_with_rules, capsys):
        # Run detect first to populate conflicts
        main(["detect", "--db", db_with_rules])
        capsys.readouterr()  # clear

        result = main(["conflicts", "--db", db_with_rules])
        assert result == 0
        output = capsys.readouterr().out
        assert "contradiction" in output

    def test_conflicts_filter_by_type(self, db_with_rules, capsys):
        main(["detect", "--db", db_with_rules])
        capsys.readouterr()

        result = main(["conflicts", "--db", db_with_rules, "--type", "dead_rule"])
        assert result == 0
        assert "No conflicts" in capsys.readouterr().out

    def test_conflicts_filter_matching(self, db_with_rules, capsys):
        main(["detect", "--db", db_with_rules])
        capsys.readouterr()

        result = main(["conflicts", "--db", db_with_rules, "--type", "contradiction"])
        assert result == 0
        output = capsys.readouterr().out
        assert "contradiction" in output


# ── analyze command (mocked) ─────────────────────────────────────────────


class TestAnalyzeCommand:
    def test_analyze_file_not_found(self):
        result = main(["analyze", "nonexistent.pdf"])
        assert result == 1

    @patch("rulelint.cli.extract_rules")
    @patch("rulelint.cli.ingest_pdf")
    def test_analyze_full_pipeline(self, mock_ingest, mock_extract, sample_rules, tmp_path, capsys):
        from rulelint.ingestion import DocumentText, PageText

        mock_ingest.return_value = DocumentText(
            source_path="test.pdf",
            pages=[PageText(page_number=1, text="Sample regulation text " * 10)],
        )
        mock_extract.return_value = sample_rules

        db_path = tmp_path / "test.db"
        # Create a fake PDF file so the path check passes
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        result = main(["analyze", str(pdf_path), "--db", str(db_path)])
        assert result == 0

        output = capsys.readouterr().out
        assert "Ingesting" in output
        assert "Extracting" in output
        assert "2 rules extracted" in output
        assert "Conflicts:" in output

        mock_ingest.assert_called_once()
        mock_extract.assert_called_once()

    @patch("rulelint.cli.extract_rules")
    @patch("rulelint.cli.ingest_pdf")
    def test_analyze_no_pages(self, mock_ingest, mock_extract, tmp_path, capsys):
        from rulelint.ingestion import DocumentText

        mock_ingest.return_value = DocumentText(source_path="test.pdf", pages=[])

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        result = main(["analyze", str(pdf_path), "--db", str(tmp_path / "test.db")])
        assert result == 1
        assert "No usable text" in capsys.readouterr().err

    @patch("rulelint.cli.extract_rules")
    @patch("rulelint.cli.ingest_pdf")
    def test_analyze_extraction_error(self, mock_ingest, mock_extract, tmp_path, capsys):
        from rulelint.extraction import ExtractionError
        from rulelint.ingestion import DocumentText, PageText

        mock_ingest.return_value = DocumentText(
            source_path="test.pdf",
            pages=[PageText(page_number=1, text="Sample text " * 10)],
        )
        mock_extract.side_effect = ExtractionError("No API key")

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        result = main(["analyze", str(pdf_path), "--db", str(tmp_path / "test.db")])
        assert result == 1
        assert "Extraction failed" in capsys.readouterr().err

    @patch("rulelint.cli.extract_rules")
    @patch("rulelint.cli.ingest_pdf")
    def test_analyze_stores_to_db(self, mock_ingest, mock_extract, sample_rules, tmp_path):
        from rulelint.ingestion import DocumentText, PageText

        mock_ingest.return_value = DocumentText(
            source_path="test.pdf",
            pages=[PageText(page_number=1, text="Sample text " * 10)],
        )
        mock_extract.return_value = sample_rules

        db_path = tmp_path / "test.db"
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        main(["analyze", str(pdf_path), "--db", str(db_path)])

        # Verify DB has rules and conflicts
        store = RuleStore(db_path)
        assert store.rule_count() == 2
        assert store.conflict_count() >= 1  # contradiction between the two rules
        store.close()

    @patch("rulelint.cli.extract_rules")
    @patch("rulelint.cli.ingest_pdf")
    def test_analyze_with_authority_hint(self, mock_ingest, mock_extract, sample_rules, tmp_path):
        from rulelint.ingestion import DocumentText, PageText

        mock_ingest.return_value = DocumentText(
            source_path="test.pdf",
            pages=[PageText(page_number=1, text="Sample text " * 10)],
        )
        mock_extract.return_value = sample_rules

        db_path = tmp_path / "test.db"
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        main(["analyze", str(pdf_path), "--db", str(db_path), "--authority", "ghmc"])

        mock_extract.assert_called_once_with(
            mock_ingest.return_value.full_text,
            authority_hint="ghmc",
            api_key=None,
        )


# ── print_summary ────────────────────────────────────────────────────────


class TestPrintSummary:
    def test_summary_no_conflicts(self, sample_rules, capsys):
        _print_summary(sample_rules, [])
        output = capsys.readouterr().out
        assert "Rules: 2" in output
        assert "Conflicts: 0" in output

    def test_summary_with_conflicts(self, sample_rules, capsys):
        conflicts = [
            Conflict(
                conflict_type=ConflictType.CONTRADICTION,
                rule_ids=["GHMC-BP-001", "HMDA-BP-001"],
                description="test",
                severity="high",
            )
        ]
        _print_summary(sample_rules, conflicts)
        output = capsys.readouterr().out
        assert "Conflicts: 1" in output
        assert "contradiction: 1" in output


# ── Integration: detect → conflicts round-trip ───────────────────────────


class TestIntegrationRoundTrip:
    def test_full_round_trip(self, tmp_path, capsys):
        """Store rules via RuleStore, then use CLI detect + conflicts."""
        from rulelint.store import RuleStore

        db_path = str(tmp_path / "rt.db")
        store = RuleStore(db_path)
        store.save_rules([
            Rule(
                rule_id="GHMC-BP-010",
                title="Max height 15m",
                description="Building height max 15m",
                authority=Authority.GHMC,
                rule_type=RuleType.REQUIREMENT,
                status=RuleStatus.ACTIVE,
                section_ref="S10",
            ),
            Rule(
                rule_id="HMDA-BP-010",
                title="No buildings over 12m",
                description="Prohibit buildings over 12m",
                authority=Authority.HMDA,
                rule_type=RuleType.PROHIBITION,
                status=RuleStatus.ACTIVE,
                section_ref="S20",
            ),
        ])
        store.close()

        # detect
        result = main(["detect", "--db", db_path])
        assert result == 0
        detect_out = capsys.readouterr().out
        assert "contradiction" in detect_out

        # conflicts
        result = main(["conflicts", "--db", db_path])
        assert result == 0
        conflicts_out = capsys.readouterr().out
        assert "GHMC-BP-010" in conflicts_out
        assert "HMDA-BP-010" in conflicts_out

        # rules
        result = main(["rules", "--db", db_path])
        assert result == 0
        rules_out = capsys.readouterr().out
        assert "2 rules total" in rules_out


# ── __main__ and public API ──────────────────────────────────────────────


class TestPackageEntry:
    def test_python_m_rulelint_runs(self):
        """python -m rulelint should be importable and callable."""
        import importlib
        mod = importlib.import_module("rulelint.__main__")
        assert hasattr(mod, "main")

    def test_public_api_exports(self):
        """Package __init__ exports all key symbols."""
        import rulelint
        for name in [
            "Rule", "Conflict", "ConflictType", "RuleType", "Authority",
            "RuleStatus", "ingest_pdf", "DocumentText", "extract_rules",
            "ExtractionError", "detect_conflicts", "RuleStore",
        ]:
            assert hasattr(rulelint, name), f"rulelint.{name} not exported"
