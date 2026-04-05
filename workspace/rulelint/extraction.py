"""LLM-based rule extraction using Claude tool_use. Layer 2 of the 3-layer architecture."""

from __future__ import annotations

import os
from typing import Any

import anthropic

from .models import Authority, Rule, RuleStatus, RuleType

# Tool schema maps 1:1 to Rule model's 13 fields.
EXTRACT_RULES_TOOL: dict[str, Any] = {
    "name": "extract_rules",
    "description": (
        "Extract structured regulation rules from the provided government document text. "
        "Each rule should be a separate object with all 13 fields populated. "
        "Call this tool once per rule found in the text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rule_id": {
                "type": "string",
                "description": "Unique ID: AUTHORITY-DOMAIN-NNN, e.g. GHMC-BP-001",
            },
            "title": {
                "type": "string",
                "description": "Short descriptive title of the rule",
            },
            "description": {
                "type": "string",
                "description": "Full text description of what the rule mandates/prohibits/permits",
            },
            "authority": {
                "type": "string",
                "enum": [a.value for a in Authority],
                "description": "Issuing authority",
            },
            "rule_type": {
                "type": "string",
                "enum": [rt.value for rt in RuleType],
                "description": "Type: requirement, prohibition, permission, or definition",
            },
            "status": {
                "type": "string",
                "enum": [s.value for s in RuleStatus],
                "description": "Current status of the rule",
            },
            "domain": {
                "type": "string",
                "description": "Domain area, e.g. building_permits",
            },
            "section_ref": {
                "type": "string",
                "description": "Section reference in the source document",
            },
            "conditions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Conditions under which the rule applies (empty array if unconditional)",
            },
            "depends_on": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Rule IDs this rule depends on (empty array if none)",
            },
            "conflicts_with": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Known conflicting rule IDs (empty array if none known)",
            },
            "supersedes": {
                "type": ["string", "null"],
                "description": "Rule ID this rule supersedes, or null",
            },
            "confidence": {
                "type": "number",
                "description": "Extraction confidence 0.0-1.0",
            },
        },
        "required": [
            "rule_id", "title", "description", "authority", "rule_type",
            "status", "domain", "section_ref", "conditions", "depends_on",
            "conflicts_with", "supersedes", "confidence",
        ],
    },
}

_SYSTEM_PROMPT = (
    "You are a legal document analyst specializing in Indian municipal regulations. "
    "Extract every distinct regulation rule from the provided text. "
    "Use the extract_rules tool once for each rule you find. "
    "Be precise with section references. Set confidence below 0.85 if the text is ambiguous. "
    "Identify dependencies between rules where one rule references another. "
    "Use the authority prefix in rule_id: GHMC-BP-NNN for GHMC rules, HMDA-BP-NNN for HMDA rules."
)


def extract_rules(
    text: str,
    authority_hint: str | None = None,
    api_key: str | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> list[Rule]:
    """Extract structured rules from document text using Claude tool_use.

    Single entry point for the extraction layer.

    Args:
        text: Clean document text (output of ingestion layer).
        authority_hint: Optional hint like "ghmc" or "hmda" to help the LLM.
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        model: Claude model to use.

    Returns:
        List of validated Rule objects.

    Raises:
        ExtractionError: If API call fails or no rules are extracted.
    """
    if not text or not text.strip():
        raise ExtractionError("Empty text provided for extraction")

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ExtractionError(
            "No API key. Set ANTHROPIC_API_KEY or pass api_key argument."
        )

    client = anthropic.Anthropic(api_key=key)

    user_msg = _build_user_message(text, authority_hint)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        tools=[EXTRACT_RULES_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": user_msg}],
    )

    rules = _parse_tool_calls(response)

    if not rules:
        raise ExtractionError("LLM returned no rules from the provided text")

    return rules


def _build_user_message(text: str, authority_hint: str | None) -> str:
    """Build the user message for the Claude API call."""
    parts = ["Extract all regulation rules from the following document text.\n"]
    if authority_hint:
        parts.append(f"This document is from: {authority_hint.upper()}\n")
    parts.append(f"---\n{text}\n---")
    return "\n".join(parts)


def _parse_tool_calls(response: anthropic.types.Message) -> list[Rule]:
    """Parse tool_use blocks from Claude response into Rule objects."""
    rules: list[Rule] = []
    for block in response.content:
        if block.type != "tool_use" or block.name != "extract_rules":
            continue
        rule = _tool_input_to_rule(block.input)
        if rule is not None:
            rules.append(rule)
    return rules


def _tool_input_to_rule(data: dict[str, Any]) -> Rule | None:
    """Convert a single tool_use input dict to a Rule. Returns None on validation failure."""
    try:
        # Normalize: conditions=None when empty list would be confusing
        if data.get("conditions") == []:
            data["conditions"] = None
        return Rule(**data)
    except Exception:
        return None


class ExtractionError(Exception):
    """Raised when rule extraction fails."""
