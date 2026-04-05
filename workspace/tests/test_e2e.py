"""End-to-end integration tests: mock PDF + mock Claude API → full pipeline → verify DB state.

Mocks ONLY external boundaries (pdfplumber, anthropic). All internal layers
(ingestion → extraction → detection → store) run for real.
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rulelint.cli import main
from rulelint.models import Authority, ConflictType, Rule, RuleStatus, RuleType
from rulelint.store import RuleStore


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_tool_use_block(rule_data: dict) -> MagicMock:
    """Create a mock tool_use content block matching anthropic response format."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "extract_rules"
    block.input = rule_data
    return block


def _make_claude_response(rule_dicts: list[dict]) -> MagicMock:
    """Create a mock anthropic Message with tool_use content blocks."""
    response = MagicMock()
    response.content = [_make_tool_use_block(d) for d in rule_dicts]
    return response


# Rule data that triggers multiple conflict types:
# - GHMC-BP-001 (requirement) vs HMDA-BP-001 (prohibition) → contradiction
# - GHMC-BP-002 depends on GHMC-BP-003, GHMC-BP-003 depends on GHMC-BP-002 → circular
# - GHMC-BP-004 (active) depends on HMDA-BP-002 (repealed) → dead_rule
# - GHMC-BP-005 supersedes HMDA-BP-003, HMDA-BP-003 supersedes HMDA-BP-004 → supersession chain (only flagged if > 2)
# - GHMC-BP-001 (requirement) vs HMDA-BP-005 (requirement, same domain, diff authority) → jurisdictional_overlap
SCENARIO_RULES = [
    {
        "rule_id": "GHMC-BP-001",
        "title": "Minimum setback 3m",
        "description": "All buildings must maintain 3m setback from road",
        "authority": "ghmc",
        "rule_type": "requirement",
        "status": "active",
        "domain": "building_permits",
        "section_ref": "Sec 5.1",
        "conditions": ["plot_area > 100sqm"],
        "depends_on": [],
        "conflicts_with": [],
        "supersedes": None,
        "confidence": 0.92,
    },
    {
        "rule_id": "HMDA-BP-001",
        "title": "No construction near road",
        "description": "Construction within 5m of road is prohibited",
        "authority": "hmda",
        "rule_type": "prohibition",
        "status": "active",
        "domain": "building_permits",
        "section_ref": "Sec 3.2",
        "conditions": [],
        "depends_on": [],
        "conflicts_with": [],
        "supersedes": None,
        "confidence": 0.88,
    },
    {
        "rule_id": "GHMC-BP-002",
        "title": "Fire exit requirement",
        "description": "Buildings over 15m must have fire exits",
        "authority": "ghmc",
        "rule_type": "requirement",
        "status": "active",
        "domain": "building_permits",
        "section_ref": "Sec 7.1",
        "conditions": ["height > 15m"],
        "depends_on": ["GHMC-BP-003"],
        "conflicts_with": [],
        "supersedes": None,
        "confidence": 0.95,
    },
    {
        "rule_id": "GHMC-BP-003",
        "title": "Structural safety clearance",
        "description": "Structural clearance needed before fire compliance",
        "authority": "ghmc",
        "rule_type": "requirement",
        "status": "active",
        "domain": "building_permits",
        "section_ref": "Sec 7.2",
        "conditions": [],
        "depends_on": ["GHMC-BP-002"],
        "conflicts_with": [],
        "supersedes": None,
        "confidence": 0.90,
    },
    {
        "rule_id": "HMDA-BP-002",
        "title": "Old drainage rule",
        "description": "Drainage plan required for plots > 200sqm",
        "authority": "hmda",
        "rule_type": "requirement",
        "status": "repealed",
        "domain": "building_permits",
        "section_ref": "Sec 4.1",
        "conditions": [],
        "depends_on": [],
        "conflicts_with": [],
        "supersedes": None,
        "confidence": 0.70,
    },
    {
        "rule_id": "GHMC-BP-004",
        "title": "Drainage compliance",
        "description": "Must comply with drainage requirements",
        "authority": "ghmc",
        "rule_type": "requirement",
        "status": "active",
        "domain": "building_permits",
        "section_ref": "Sec 8.1",
        "conditions": [],
        "depends_on": ["HMDA-BP-002"],
        "conflicts_with": [],
        "supersedes": None,
        "confidence": 0.85,
    },
    {
        "rule_id": "GHMC-BP-005",
        "title": "Updated parking rule v3",
        "description": "Parking requirements revised again",
        "authority": "ghmc",
        "rule_type": "requirement",
        "status": "active",
        "domain": "building_permits",
        "section_ref": "Sec 9.3",
        "conditions": [],
        "depends_on": [],
        "conflicts_with": [],
        "supersedes": "HMDA-BP-003",
        "confidence": 0.93,
    },
    {
        "rule_id": "HMDA-BP-003",
        "title": "Updated parking rule v2",
        "description": "Parking requirements revised",
        "authority": "hmda",
        "rule_type": "requirement",
        "status": "superseded",
        "domain": "building_permits",
        "section_ref": "Sec 9.2",
        "conditions": [],
        "depends_on": [],
        "conflicts_with": [],
        "supersedes": "HMDA-BP-004",
        "confidence": 0.87,
    },
    {
        "rule_id": "HMDA-BP-004",
        "title": "Original parking rule",
        "description": "Original parking requirements",
        "authority": "hmda",
        "rule_type": "requirement",
        "status": "superseded",
        "domain": "building_permits",
        "section_ref": "Sec 9.1",
        "conditions": [],
        "depends_on": [],
        "conflicts_with": [],
        "supersedes": None,
        "confidence": 0.91,
    },
    {
        "rule_id": "HMDA-BP-005",
        "title": "Setback from boundary",
        "description": "Minimum 2m setback from property boundary",
        "authority": "hmda",
        "rule_type": "requirement",
        "status": "active",
        "domain": "building_permits",
        "section_ref": "Sec 5.5",
        "conditions": [],
        "depends_on": [],
        "conflicts_with": [],
        "supersedes": None,
        "confidence": 0.96,
    },
]


# ── E2E Tests ────────────────────────────────────────────────────────────


class TestE2EAnalyzePipeline:
    """Full pipeline: mock PDF file → mock Claude API → real detection → real DB."""

    @patch("rulelint.extraction.anthropic.Anthropic")
    @patch("rulelint.ingestion.pdfplumber.open")
    def test_analyze_stores_rules_and_detects_conflicts(
        self, mock_pdfplumber_open, mock_anthropic_cls, tmp_path
    ):
        """Core e2e: analyze a mocked PDF, verify rules + conflicts in DB."""
        # Mock pdfplumber: one page of "regulation text"
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "GHMC Building Regulations 2024\n"
            "Section 5.1: All buildings must maintain 3m setback from road.\n"
            "Section 7.1: Buildings over 15m require fire exits.\n"
            "This is enough text to pass the 20-char usability check easily."
        )
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber_open.return_value = mock_pdf

        # Mock anthropic client: return tool_use blocks for all scenario rules
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_claude_response(SCENARIO_RULES)

        # Create fake PDF file
        pdf_path = tmp_path / "regulations.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content")
        db_path = tmp_path / "e2e_test.db"

        # Run the full pipeline
        result = main([
            "analyze", str(pdf_path),
            "--db", str(db_path),
            "--api-key", "test-key-e2e",
            "--authority", "ghmc",
        ])
        assert result == 0

        # Verify DB state
        with RuleStore(db_path) as store:
            rules = store.get_all_rules()
            conflicts = store.get_conflicts()

            # All 10 rules should be stored
            assert len(rules) == 10
            rule_ids = {r.rule_id for r in rules}
            assert "GHMC-BP-001" in rule_ids
            assert "HMDA-BP-001" in rule_ids
            assert "GHMC-BP-005" in rule_ids

            # Verify rule fields survived the full pipeline
            r1 = store.get_rule("GHMC-BP-001")
            assert r1 is not None
            assert r1.authority == Authority.GHMC
            assert r1.rule_type == RuleType.REQUIREMENT
            assert r1.confidence == 0.92
            assert r1.conditions == ["plot_area > 100sqm"]

            # Verify multiple conflict types were detected
            conflict_types = {c.conflict_type for c in conflicts}
            assert ConflictType.CONTRADICTION in conflict_types
            assert ConflictType.CIRCULAR_DEPENDENCY in conflict_types
            assert ConflictType.DEAD_RULE in conflict_types

            # At least 3 conflicts total
            assert len(conflicts) >= 3

    @patch("rulelint.extraction.anthropic.Anthropic")
    @patch("rulelint.ingestion.pdfplumber.open")
    def test_analyze_then_cli_queries(
        self, mock_pdfplumber_open, mock_anthropic_cls, tmp_path, capsys
    ):
        """After analyze, verify CLI 'rules' and 'conflicts' commands work on the DB."""
        # Same mocking setup
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Enough regulation text " * 20
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber_open.return_value = mock_pdf

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_claude_response(SCENARIO_RULES)

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        db_path = str(tmp_path / "e2e_query.db")

        # Step 1: Analyze
        result = main(["analyze", str(pdf_path), "--db", db_path, "--api-key", "k"])
        assert result == 0
        capsys.readouterr()  # clear output

        # Step 2: List rules via CLI
        result = main(["rules", "--db", db_path])
        assert result == 0
        rules_out = capsys.readouterr().out
        assert "10 rules total" in rules_out
        # D5 compliance: low-confidence rule (HMDA-BP-002 at 0.70) should show warning
        assert "conf=70%" in rules_out
        assert "manual review" in rules_out

        # Step 3: List conflicts via CLI
        result = main(["conflicts", "--db", db_path])
        assert result == 0
        conflicts_out = capsys.readouterr().out
        assert "contradiction" in conflicts_out.lower()

        # Step 4: Filter conflicts by type
        result = main(["conflicts", "--db", db_path, "--type", "circular_dependency"])
        assert result == 0
        filtered_out = capsys.readouterr().out
        assert "circular" in filtered_out.lower() or "Circular" in filtered_out

    @patch("rulelint.extraction.anthropic.Anthropic")
    @patch("rulelint.ingestion.pdfplumber.open")
    def test_analyze_two_pdfs_incremental(
        self, mock_pdfplumber_open, mock_anthropic_cls, tmp_path
    ):
        """Analyze two PDFs sequentially — second run should see ALL rules for detection."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Regulation text content " * 20
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber_open.return_value = mock_pdf

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        db_path = str(tmp_path / "incremental.db")

        # First PDF: one GHMC requirement rule
        batch1 = [SCENARIO_RULES[0]]  # GHMC-BP-001 requirement
        mock_client.messages.create.return_value = _make_claude_response(batch1)

        pdf1 = tmp_path / "ghmc.pdf"
        pdf1.write_bytes(b"%PDF-1.4 ghmc")
        result = main(["analyze", str(pdf1), "--db", db_path, "--api-key", "k"])
        assert result == 0

        with RuleStore(db_path) as store:
            assert store.rule_count() == 1
            assert store.conflict_count() == 0  # single rule, no conflicts

        # Second PDF: one HMDA prohibition rule (will conflict with first)
        batch2 = [SCENARIO_RULES[1]]  # HMDA-BP-001 prohibition
        mock_client.messages.create.return_value = _make_claude_response(batch2)

        pdf2 = tmp_path / "hmda.pdf"
        pdf2.write_bytes(b"%PDF-1.4 hmda")
        result = main(["analyze", str(pdf2), "--db", db_path, "--api-key", "k"])
        assert result == 0

        with RuleStore(db_path) as store:
            assert store.rule_count() == 2
            # Now detection ran on both rules → should find contradiction
            conflicts = store.get_conflicts()
            assert any(c.conflict_type == ConflictType.CONTRADICTION for c in conflicts)

    @patch("rulelint.extraction.anthropic.Anthropic")
    @patch("rulelint.ingestion.pdfplumber.open")
    def test_analyze_low_confidence_rules_preserved(
        self, mock_pdfplumber_open, mock_anthropic_cls, tmp_path
    ):
        """Rules with low confidence (< 85%) should be stored and flagged per D5."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Document text " * 20
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber_open.return_value = mock_pdf

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # One high-confidence, one low-confidence rule
        low_conf_rules = [SCENARIO_RULES[0], SCENARIO_RULES[4]]  # 0.92 and 0.70
        mock_client.messages.create.return_value = _make_claude_response(low_conf_rules)

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        db_path = str(tmp_path / "conf.db")

        result = main(["analyze", str(pdf_path), "--db", db_path, "--api-key", "k"])
        assert result == 0

        with RuleStore(db_path) as store:
            low = store.get_rule("HMDA-BP-002")
            assert low is not None
            assert low.confidence == 0.70
            assert low.status == RuleStatus.REPEALED

    @patch("rulelint.extraction.anthropic.Anthropic")
    @patch("rulelint.ingestion.pdfplumber.open")
    def test_supersession_chain_detected(
        self, mock_pdfplumber_open, mock_anthropic_cls, tmp_path
    ):
        """Verify supersession chains > 2 are flagged through the full pipeline."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Parking regulations " * 20
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber_open.return_value = mock_pdf

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # 3-rule supersession chain: GHMC-BP-005 → HMDA-BP-003 → HMDA-BP-004
        chain_rules = [SCENARIO_RULES[6], SCENARIO_RULES[7], SCENARIO_RULES[8]]
        mock_client.messages.create.return_value = _make_claude_response(chain_rules)

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        db_path = str(tmp_path / "chain.db")

        result = main(["analyze", str(pdf_path), "--db", db_path, "--api-key", "k"])
        assert result == 0

        with RuleStore(db_path) as store:
            conflicts = store.get_conflicts()
            chain_conflicts = [
                c for c in conflicts if c.conflict_type == ConflictType.SUPERSESSION_CHAIN
            ]
            assert len(chain_conflicts) >= 1
            assert "GHMC-BP-005" in chain_conflicts[0].rule_ids
