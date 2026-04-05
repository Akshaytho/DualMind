"""Tests for models.py — schema validation."""

import pytest
from pydantic import ValidationError

from rulelint.models import Authority, Conflict, ConflictType, Rule, RuleStatus, RuleType


class TestRuleModel:
    def test_minimal_rule(self):
        r = Rule(
            rule_id="TEST-001",
            title="Test rule",
            description="A test",
            authority=Authority.GHMC,
            rule_type=RuleType.REQUIREMENT,
            section_ref="SEC-1.0",
        )
        assert r.rule_id == "TEST-001"
        assert r.status == RuleStatus.ACTIVE
        assert r.conditions is None
        assert r.depends_on == []
        assert r.confidence == 1.0

    def test_full_rule(self):
        r = Rule(
            rule_id="TEST-002",
            title="Full rule",
            description="All fields",
            authority=Authority.HMDA,
            rule_type=RuleType.PROHIBITION,
            status=RuleStatus.REPEALED,
            domain="building_permits",
            section_ref="SEC-2.0",
            conditions=["x > 5"],
            depends_on=["TEST-001"],
            conflicts_with=["TEST-003"],
            supersedes="TEST-000",
            confidence=0.85,
        )
        assert r.authority == "hmda"
        assert r.supersedes == "TEST-000"

    def test_invalid_authority_rejected(self):
        with pytest.raises(ValidationError):
            Rule(
                rule_id="BAD-001",
                title="Bad",
                description="Bad authority",
                authority="unknown_authority",
                rule_type=RuleType.REQUIREMENT,
                section_ref="SEC-1.0",
            )

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            Rule(
                rule_id="BAD-002",
                title="Bad",
                description="Bad confidence",
                authority=Authority.GHMC,
                rule_type=RuleType.REQUIREMENT,
                section_ref="SEC-1.0",
                confidence=1.5,
            )

    def test_strenum_values(self):
        assert RuleType.REQUIREMENT == "requirement"
        assert Authority.GHMC == "ghmc"
        assert RuleStatus.ACTIVE == "active"


class TestConflictModel:
    def test_conflict_creation(self):
        c = Conflict(
            conflict_type=ConflictType.CONTRADICTION,
            rule_ids=["A", "B"],
            description="A contradicts B",
        )
        assert c.severity == "medium"

    def test_conflict_needs_at_least_one_rule(self):
        with pytest.raises(ValidationError):
            Conflict(
                conflict_type=ConflictType.DEAD_RULE,
                rule_ids=[],
                description="No rules",
            )
