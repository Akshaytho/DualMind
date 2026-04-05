"""Shared fixtures for RuleLint tests."""

import json
from pathlib import Path

import pytest

from rulelint.models import Rule


@pytest.fixture
def ground_truth_rules() -> list[Rule]:
    """Load the 15 hand-extracted ground truth rules."""
    path = Path(__file__).parent / "ground_truth.json"
    return [Rule(**r) for r in json.loads(path.read_text())]


@pytest.fixture
def active_rules(ground_truth_rules: list[Rule]) -> list[Rule]:
    """Only active rules from ground truth."""
    return [r for r in ground_truth_rules if r.status == "active"]
