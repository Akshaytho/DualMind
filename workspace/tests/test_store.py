"""Tests for store.py — SQLite CRUD for rules and conflicts."""

import pytest

from rulelint.models import Authority, Conflict, ConflictType, Rule, RuleStatus, RuleType
from rulelint.store import RuleStore


@pytest.fixture
def store():
    """In-memory store for each test."""
    s = RuleStore(":memory:")
    yield s
    s.close()


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


# ── Rule CRUD ──────────────────────────────────────────────────────────────


class TestRuleCRUD:
    def test_save_and_get(self, store: RuleStore):
        rule = _make_rule()
        store.save_rule(rule, source_file="test.pdf")
        loaded = store.get_rule("TEST-001")
        assert loaded is not None
        assert loaded.rule_id == "TEST-001"
        assert loaded.authority == Authority.GHMC

    def test_get_missing_returns_none(self, store: RuleStore):
        assert store.get_rule("NOPE") is None

    def test_save_replaces_existing(self, store: RuleStore):
        store.save_rule(_make_rule(title="v1"))
        store.save_rule(_make_rule(title="v2"))
        loaded = store.get_rule("TEST-001")
        assert loaded is not None
        assert loaded.title == "v2"
        assert store.rule_count() == 1

    def test_get_all_rules(self, store: RuleStore):
        store.save_rule(_make_rule(rule_id="A"))
        store.save_rule(_make_rule(rule_id="B"))
        store.save_rule(_make_rule(rule_id="C"))
        all_rules = store.get_all_rules()
        assert len(all_rules) == 3
        assert [r.rule_id for r in all_rules] == ["A", "B", "C"]

    def test_delete_rule(self, store: RuleStore):
        store.save_rule(_make_rule())
        assert store.delete_rule("TEST-001") is True
        assert store.get_rule("TEST-001") is None
        assert store.rule_count() == 0

    def test_delete_nonexistent(self, store: RuleStore):
        assert store.delete_rule("NOPE") is False

    def test_bulk_save(self, store: RuleStore):
        rules = [_make_rule(rule_id=f"R-{i}") for i in range(10)]
        count = store.save_rules(rules, source_file="bulk.pdf")
        assert count == 10
        assert store.rule_count() == 10

    def test_rule_count_empty(self, store: RuleStore):
        assert store.rule_count() == 0


# ── Conflict CRUD ──────────────────────────────────────────────────────────


class TestConflictCRUD:
    def test_save_and_get_conflicts(self, store: RuleStore):
        conflicts = [
            Conflict(
                conflict_type=ConflictType.CONTRADICTION,
                rule_ids=["A", "B"],
                description="A vs B",
                severity="high",
            ),
            Conflict(
                conflict_type=ConflictType.DEAD_RULE,
                rule_ids=["C", "D"],
                description="C depends on dead D",
            ),
        ]
        store.save_conflicts(conflicts)
        assert store.conflict_count() == 2

    def test_get_conflicts_by_type(self, store: RuleStore):
        conflicts = [
            Conflict(conflict_type=ConflictType.CONTRADICTION, rule_ids=["A", "B"], description="x"),
            Conflict(conflict_type=ConflictType.DEAD_RULE, rule_ids=["C", "D"], description="y"),
            Conflict(conflict_type=ConflictType.CONTRADICTION, rule_ids=["E", "F"], description="z"),
        ]
        store.save_conflicts(conflicts)
        contras = store.get_conflicts(ConflictType.CONTRADICTION)
        assert len(contras) == 2
        deads = store.get_conflicts(ConflictType.DEAD_RULE)
        assert len(deads) == 1

    def test_save_conflicts_clears_previous(self, store: RuleStore):
        """Re-detection replaces old conflicts."""
        store.save_conflicts([
            Conflict(conflict_type=ConflictType.CONTRADICTION, rule_ids=["A", "B"], description="old"),
        ])
        assert store.conflict_count() == 1
        store.save_conflicts([
            Conflict(conflict_type=ConflictType.DEAD_RULE, rule_ids=["X", "Y"], description="new"),
        ])
        assert store.conflict_count() == 1
        conflicts = store.get_conflicts()
        assert conflicts[0].conflict_type == ConflictType.DEAD_RULE

    def test_conflict_roundtrip_preserves_data(self, store: RuleStore):
        original = Conflict(
            conflict_type=ConflictType.CIRCULAR_DEPENDENCY,
            rule_ids=["A", "B", "C"],
            description="A → B → C → A",
            severity="high",
        )
        store.save_conflicts([original])
        loaded = store.get_conflicts()[0]
        assert loaded.conflict_type == original.conflict_type
        assert loaded.rule_ids == original.rule_ids
        assert loaded.description == original.description
        assert loaded.severity == original.severity


# ── Integration with ground truth ──────────────────────────────────────────


class TestStoreIntegration:
    def test_store_ground_truth_rules(self, store: RuleStore, ground_truth_rules):
        """Round-trip: save all 15 ground truth rules, load them back."""
        count = store.save_rules(ground_truth_rules)
        assert count == 15
        loaded = store.get_all_rules()
        assert len(loaded) == 15
        # Verify a specific rule survived the round-trip
        rule = store.get_rule("GHMC-BP-003")
        assert rule is not None
        assert rule.authority == Authority.GHMC
        assert rule.rule_type == RuleType.PROHIBITION

    def test_detect_and_store_conflicts(self, store: RuleStore, ground_truth_rules):
        """End-to-end: store rules → detect → store conflicts → read back."""
        from rulelint.detection import detect_conflicts

        store.save_rules(ground_truth_rules)
        conflicts = detect_conflicts(ground_truth_rules)
        store.save_conflicts(conflicts)
        assert store.conflict_count() > 0
        contras = store.get_conflicts(ConflictType.CONTRADICTION)
        assert any({"GHMC-BP-003", "HMDA-BP-003"} == set(c.rule_ids) for c in contras)
