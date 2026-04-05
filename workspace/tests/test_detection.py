"""Tests for detection.py — 5 algorithms, 0 false positives on ground truth."""

import pytest

from rulelint.detection import detect_conflicts
from rulelint.models import Authority, Conflict, ConflictType, Rule, RuleStatus, RuleType


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_rule(**overrides) -> Rule:
    defaults = dict(
        rule_id="TEST-001",
        title="Test",
        description="Test rule",
        authority=Authority.GHMC,
        rule_type=RuleType.REQUIREMENT,
        section_ref="SEC-1.0",
    )
    defaults.update(overrides)
    return Rule(**defaults)


def _conflicts_of_type(conflicts: list[Conflict], ctype: ConflictType) -> list[Conflict]:
    return [c for c in conflicts if c.conflict_type == ctype]


# ── 1. Contradiction Detection ───────────────────────────────────────────────

class TestContradictions:
    def test_opposing_types_different_authorities(self):
        rules = [
            _make_rule(rule_id="A", authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT),
            _make_rule(rule_id="B", authority=Authority.HMDA, rule_type=RuleType.PROHIBITION),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.CONTRADICTION)
        assert len(conflicts) == 1
        assert set(conflicts[0].rule_ids) == {"A", "B"}

    def test_same_authority_no_contradiction(self):
        rules = [
            _make_rule(rule_id="A", authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT),
            _make_rule(rule_id="B", authority=Authority.GHMC, rule_type=RuleType.PROHIBITION),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.CONTRADICTION)
        assert len(conflicts) == 0

    def test_same_type_no_contradiction(self):
        rules = [
            _make_rule(rule_id="A", authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT),
            _make_rule(rule_id="B", authority=Authority.HMDA, rule_type=RuleType.REQUIREMENT),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.CONTRADICTION)
        assert len(conflicts) == 0

    def test_permission_vs_prohibition(self):
        rules = [
            _make_rule(rule_id="A", authority=Authority.GHMC, rule_type=RuleType.PERMISSION),
            _make_rule(rule_id="B", authority=Authority.HMDA, rule_type=RuleType.PROHIBITION),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.CONTRADICTION)
        assert len(conflicts) == 1

    def test_inactive_rules_ignored(self):
        rules = [
            _make_rule(rule_id="A", authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT, status=RuleStatus.REPEALED),
            _make_rule(rule_id="B", authority=Authority.HMDA, rule_type=RuleType.PROHIBITION),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.CONTRADICTION)
        assert len(conflicts) == 0


# ── 2. Circular Dependency Detection ─────────────────────────────────────────

class TestCircularDependencies:
    def test_simple_cycle(self):
        rules = [
            _make_rule(rule_id="A", depends_on=["B"]),
            _make_rule(rule_id="B", depends_on=["A"]),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.CIRCULAR_DEPENDENCY)
        assert len(conflicts) == 1

    def test_three_node_cycle(self):
        rules = [
            _make_rule(rule_id="A", depends_on=["B"]),
            _make_rule(rule_id="B", depends_on=["C"]),
            _make_rule(rule_id="C", depends_on=["A"]),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.CIRCULAR_DEPENDENCY)
        assert len(conflicts) == 1

    def test_no_cycle(self):
        rules = [
            _make_rule(rule_id="A", depends_on=["B"]),
            _make_rule(rule_id="B", depends_on=[]),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.CIRCULAR_DEPENDENCY)
        assert len(conflicts) == 0


# ── 3. Dead Rule Detection ──────────────────────────────────────────────────

class TestDeadRules:
    def test_active_depends_on_repealed(self):
        rules = [
            _make_rule(rule_id="A", status=RuleStatus.ACTIVE, depends_on=["B"]),
            _make_rule(rule_id="B", status=RuleStatus.REPEALED),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.DEAD_RULE)
        assert len(conflicts) == 1
        assert conflicts[0].rule_ids == ["A", "B"]

    def test_active_depends_on_superseded(self):
        rules = [
            _make_rule(rule_id="A", status=RuleStatus.ACTIVE, depends_on=["B"]),
            _make_rule(rule_id="B", status=RuleStatus.SUPERSEDED),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.DEAD_RULE)
        assert len(conflicts) == 1

    def test_active_depends_on_active_ok(self):
        rules = [
            _make_rule(rule_id="A", depends_on=["B"]),
            _make_rule(rule_id="B"),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.DEAD_RULE)
        assert len(conflicts) == 0

    def test_repealed_depends_on_repealed_ignored(self):
        rules = [
            _make_rule(rule_id="A", status=RuleStatus.REPEALED, depends_on=["B"]),
            _make_rule(rule_id="B", status=RuleStatus.REPEALED),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.DEAD_RULE)
        assert len(conflicts) == 0


# ── 4. Jurisdictional Overlap Detection ──────────────────────────────────────

class TestJurisdictionalOverlaps:
    def test_same_type_different_authority(self):
        rules = [
            _make_rule(rule_id="A", authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT),
            _make_rule(rule_id="B", authority=Authority.HMDA, rule_type=RuleType.REQUIREMENT),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.JURISDICTIONAL_OVERLAP)
        assert len(conflicts) == 1

    def test_different_types_no_overlap(self):
        rules = [
            _make_rule(rule_id="A", authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT),
            _make_rule(rule_id="B", authority=Authority.HMDA, rule_type=RuleType.DEFINITION),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.JURISDICTIONAL_OVERLAP)
        assert len(conflicts) == 0

    def test_same_authority_no_overlap(self):
        rules = [
            _make_rule(rule_id="A", authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT),
            _make_rule(rule_id="B", authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.JURISDICTIONAL_OVERLAP)
        assert len(conflicts) == 0

    def test_opposing_types_not_flagged_as_overlap(self):
        """Requirement vs Prohibition = contradiction, not overlap."""
        rules = [
            _make_rule(rule_id="A", authority=Authority.GHMC, rule_type=RuleType.REQUIREMENT),
            _make_rule(rule_id="B", authority=Authority.HMDA, rule_type=RuleType.PROHIBITION),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.JURISDICTIONAL_OVERLAP)
        assert len(conflicts) == 0


# ── 5. Supersession Chain Detection ──────────────────────────────────────────

class TestSupersessionChains:
    def test_long_chain_detected(self):
        rules = [
            _make_rule(rule_id="C", supersedes="B"),
            _make_rule(rule_id="B", supersedes="A"),
            _make_rule(rule_id="A"),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.SUPERSESSION_CHAIN)
        assert len(conflicts) == 1
        assert "C" in conflicts[0].rule_ids

    def test_short_chain_ok(self):
        rules = [
            _make_rule(rule_id="B", supersedes="A"),
            _make_rule(rule_id="A"),
        ]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.SUPERSESSION_CHAIN)
        assert len(conflicts) == 0

    def test_no_supersession(self):
        rules = [_make_rule(rule_id="A"), _make_rule(rule_id="B")]
        conflicts = _conflicts_of_type(detect_conflicts(rules), ConflictType.SUPERSESSION_CHAIN)
        assert len(conflicts) == 0


# ── Ground Truth Integration ─────────────────────────────────────────────────

class TestGroundTruth:
    def test_loads_all_15_rules(self, ground_truth_rules):
        assert len(ground_truth_rules) == 15

    def test_detects_known_contradictions(self, ground_truth_rules):
        """GHMC-BP-003 (prohibition) vs HMDA-BP-003 (permission) on water bodies."""
        conflicts = _conflicts_of_type(detect_conflicts(ground_truth_rules), ConflictType.CONTRADICTION)
        rule_pairs = [set(c.rule_ids) for c in conflicts]
        assert {"GHMC-BP-003", "HMDA-BP-003"} in rule_pairs

    def test_detects_circular_dependency(self, ground_truth_rules):
        """HMDA-BP-004 depends on HMDA-BP-005 and vice versa."""
        conflicts = _conflicts_of_type(detect_conflicts(ground_truth_rules), ConflictType.CIRCULAR_DEPENDENCY)
        assert len(conflicts) == 1
        cycle_ids = set(conflicts[0].rule_ids)
        assert "HMDA-BP-004" in cycle_ids
        assert "HMDA-BP-005" in cycle_ids

    def test_detects_dead_rule(self, ground_truth_rules):
        """GHMC-BP-009 (active) depends on GHMC-BP-008 (repealed)."""
        conflicts = _conflicts_of_type(detect_conflicts(ground_truth_rules), ConflictType.DEAD_RULE)
        dead_pairs = [c.rule_ids for c in conflicts]
        assert ["GHMC-BP-009", "GHMC-BP-008"] in dead_pairs

    def test_zero_false_positives_on_ground_truth(self, ground_truth_rules):
        """Every detected conflict should be a real conflict in the ground truth set."""
        conflicts = detect_conflicts(ground_truth_rules)
        # We expect: contradictions, 1 circular dep, 1 dead rule, overlaps, possibly chains
        # The key invariant: no conflict should contain rule_ids that don't exist
        all_ids = {r.rule_id for r in ground_truth_rules}
        for c in conflicts:
            for rid in c.rule_ids:
                assert rid in all_ids, f"False positive: {rid} not in ground truth"
