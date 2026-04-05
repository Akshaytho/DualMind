"""Tests for extraction.py — Claude tool_use rule extraction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from rulelint.extraction import (
    EXTRACT_RULES_TOOL,
    ExtractionError,
    _build_user_message,
    _parse_tool_calls,
    _tool_input_to_rule,
    extract_rules,
)
from rulelint.models import Authority, Rule, RuleStatus, RuleType


# ── Fixtures ─────────────────────────────────────────────────────────────

SAMPLE_TOOL_INPUT = {
    "rule_id": "GHMC-BP-100",
    "title": "Test height restriction",
    "description": "Max 10m in residential zones",
    "authority": "ghmc",
    "rule_type": "requirement",
    "status": "active",
    "domain": "building_permits",
    "section_ref": "GHMC-Test-1.0",
    "conditions": ["zone_type == residential"],
    "depends_on": [],
    "conflicts_with": [],
    "supersedes": None,
    "confidence": 0.92,
}

SAMPLE_TOOL_INPUT_2 = {
    "rule_id": "HMDA-BP-100",
    "title": "HMDA setback rule",
    "description": "3m front setback for commercial",
    "authority": "hmda",
    "rule_type": "requirement",
    "status": "active",
    "domain": "building_permits",
    "section_ref": "HMDA-Test-2.0",
    "conditions": ["building_type == commercial"],
    "depends_on": ["GHMC-BP-100"],
    "conflicts_with": [],
    "supersedes": None,
    "confidence": 0.88,
}


def _make_tool_use_block(name: str, input_data: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=input_data)


def _make_text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _make_response(content: list) -> SimpleNamespace:
    return SimpleNamespace(content=content)


# ── Tool schema tests ────────────────────────────────────────────────────


class TestToolSchema:
    def test_schema_has_all_13_fields(self):
        props = EXTRACT_RULES_TOOL["input_schema"]["properties"]
        expected = {
            "rule_id", "title", "description", "authority", "rule_type",
            "status", "domain", "section_ref", "conditions", "depends_on",
            "conflicts_with", "supersedes", "confidence",
        }
        assert set(props.keys()) == expected

    def test_schema_required_matches_properties(self):
        props = set(EXTRACT_RULES_TOOL["input_schema"]["properties"].keys())
        required = set(EXTRACT_RULES_TOOL["input_schema"]["required"])
        assert required == props

    def test_authority_enum_matches_model(self):
        schema_enum = EXTRACT_RULES_TOOL["input_schema"]["properties"]["authority"]["enum"]
        model_values = [a.value for a in Authority]
        assert schema_enum == model_values

    def test_rule_type_enum_matches_model(self):
        schema_enum = EXTRACT_RULES_TOOL["input_schema"]["properties"]["rule_type"]["enum"]
        model_values = [rt.value for rt in RuleType]
        assert schema_enum == model_values

    def test_status_enum_matches_model(self):
        schema_enum = EXTRACT_RULES_TOOL["input_schema"]["properties"]["status"]["enum"]
        model_values = [s.value for s in RuleStatus]
        assert schema_enum == model_values


# ── _tool_input_to_rule tests ────────────────────────────────────────────


class TestToolInputToRule:
    def test_valid_input_returns_rule(self):
        rule = _tool_input_to_rule(SAMPLE_TOOL_INPUT.copy())
        assert isinstance(rule, Rule)
        assert rule.rule_id == "GHMC-BP-100"
        assert rule.authority == Authority.GHMC
        assert rule.confidence == 0.92

    def test_empty_conditions_becomes_none(self):
        data = SAMPLE_TOOL_INPUT.copy()
        data["conditions"] = []
        rule = _tool_input_to_rule(data)
        assert rule is not None
        assert rule.conditions is None

    def test_non_empty_conditions_preserved(self):
        data = SAMPLE_TOOL_INPUT.copy()
        data["conditions"] = ["zone_type == residential"]
        rule = _tool_input_to_rule(data)
        assert rule.conditions == ["zone_type == residential"]

    def test_invalid_authority_returns_none(self):
        data = SAMPLE_TOOL_INPUT.copy()
        data["authority"] = "invalid_authority"
        assert _tool_input_to_rule(data) is None

    def test_confidence_out_of_range_returns_none(self):
        data = SAMPLE_TOOL_INPUT.copy()
        data["confidence"] = 1.5
        assert _tool_input_to_rule(data) is None

    def test_missing_required_field_returns_none(self):
        data = SAMPLE_TOOL_INPUT.copy()
        del data["rule_id"]
        assert _tool_input_to_rule(data) is None

    def test_supersedes_string(self):
        data = SAMPLE_TOOL_INPUT.copy()
        data["supersedes"] = "GHMC-BP-050"
        rule = _tool_input_to_rule(data)
        assert rule.supersedes == "GHMC-BP-050"


# ── _parse_tool_calls tests ─────────────────────────────────────────────


class TestParseToolCalls:
    def test_single_tool_use(self):
        response = _make_response([_make_tool_use_block("extract_rules", SAMPLE_TOOL_INPUT.copy())])
        rules = _parse_tool_calls(response)
        assert len(rules) == 1
        assert rules[0].rule_id == "GHMC-BP-100"

    def test_multiple_tool_uses(self):
        response = _make_response([
            _make_tool_use_block("extract_rules", SAMPLE_TOOL_INPUT.copy()),
            _make_tool_use_block("extract_rules", SAMPLE_TOOL_INPUT_2.copy()),
        ])
        rules = _parse_tool_calls(response)
        assert len(rules) == 2
        assert rules[0].rule_id == "GHMC-BP-100"
        assert rules[1].rule_id == "HMDA-BP-100"

    def test_ignores_text_blocks(self):
        response = _make_response([
            _make_text_block("I found some rules"),
            _make_tool_use_block("extract_rules", SAMPLE_TOOL_INPUT.copy()),
        ])
        rules = _parse_tool_calls(response)
        assert len(rules) == 1

    def test_ignores_wrong_tool_name(self):
        response = _make_response([
            _make_tool_use_block("some_other_tool", SAMPLE_TOOL_INPUT.copy()),
        ])
        rules = _parse_tool_calls(response)
        assert len(rules) == 0

    def test_skips_invalid_inputs(self):
        bad_data = SAMPLE_TOOL_INPUT.copy()
        bad_data["authority"] = "invalid"
        response = _make_response([
            _make_tool_use_block("extract_rules", bad_data),
            _make_tool_use_block("extract_rules", SAMPLE_TOOL_INPUT_2.copy()),
        ])
        rules = _parse_tool_calls(response)
        assert len(rules) == 1
        assert rules[0].rule_id == "HMDA-BP-100"

    def test_empty_response(self):
        response = _make_response([])
        assert _parse_tool_calls(response) == []


# ── _build_user_message tests ───────────────────────────────────────────


class TestBuildUserMessage:
    def test_basic_message(self):
        msg = _build_user_message("Some regulation text", None)
        assert "Some regulation text" in msg
        assert "---" in msg

    def test_with_authority_hint(self):
        msg = _build_user_message("Some text", "ghmc")
        assert "GHMC" in msg
        assert "Some text" in msg

    def test_no_authority_hint(self):
        msg = _build_user_message("Some text", None)
        assert "document is from" not in msg


# ── extract_rules integration tests (mocked API) ────────────────────────


class TestExtractRules:
    def test_empty_text_raises(self):
        with pytest.raises(ExtractionError, match="Empty text"):
            extract_rules("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ExtractionError, match="Empty text"):
            extract_rules("   \n  ")

    def test_no_api_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ExtractionError, match="No API key"):
                extract_rules("Some regulation text", api_key=None)

    @patch("rulelint.extraction.anthropic.Anthropic")
    def test_successful_extraction(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_response([
            _make_tool_use_block("extract_rules", SAMPLE_TOOL_INPUT.copy()),
            _make_tool_use_block("extract_rules", SAMPLE_TOOL_INPUT_2.copy()),
        ])

        rules = extract_rules("Some regulation text", api_key="test-key")
        assert len(rules) == 2
        assert rules[0].rule_id == "GHMC-BP-100"
        assert rules[1].rule_id == "HMDA-BP-100"

        # Verify API was called with correct params
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["tools"] == [EXTRACT_RULES_TOOL]
        assert call_kwargs["tool_choice"] == {"type": "any"}

    @patch("rulelint.extraction.anthropic.Anthropic")
    def test_no_rules_extracted_raises(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_response([
            _make_text_block("I couldn't find any rules"),
        ])

        with pytest.raises(ExtractionError, match="no rules"):
            extract_rules("Some text", api_key="test-key")

    @patch("rulelint.extraction.anthropic.Anthropic")
    def test_authority_hint_passed_to_message(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_response([
            _make_tool_use_block("extract_rules", SAMPLE_TOOL_INPUT.copy()),
        ])

        extract_rules("Some text", authority_hint="hmda", api_key="test-key")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "HMDA" in user_content

    @patch("rulelint.extraction.anthropic.Anthropic")
    def test_env_var_api_key(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_response([
            _make_tool_use_block("extract_rules", SAMPLE_TOOL_INPUT.copy()),
        ])

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}):
            extract_rules("Some text")

        mock_anthropic_cls.assert_called_with(api_key="env-key")
