"""Pydantic models for RuleLint rule schema (D3: 13 fields)."""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field


class RuleType(StrEnum):
    REQUIREMENT = "requirement"
    PROHIBITION = "prohibition"
    PERMISSION = "permission"
    DEFINITION = "definition"


class Authority(StrEnum):
    GHMC = "ghmc"
    HMDA = "hmda"


class RuleStatus(StrEnum):
    ACTIVE = "active"
    REPEALED = "repealed"
    SUPERSEDED = "superseded"
    DRAFT = "draft"


class Rule(BaseModel):
    """A single regulation rule extracted from a government document."""

    rule_id: str = Field(..., description="Unique identifier, e.g. GHMC-BP-001")
    title: str
    description: str
    authority: Authority
    rule_type: RuleType
    status: RuleStatus = RuleStatus.ACTIVE
    domain: str = "building_permits"
    section_ref: str = Field(..., description="Section reference in source document")
    conditions: Optional[list[str]] = None
    depends_on: list[str] = Field(default_factory=list, description="List of rule_ids this rule depends on")
    conflicts_with: list[str] = Field(default_factory=list, description="Known conflicts (manual annotation)")
    supersedes: Optional[str] = None
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Extraction confidence score")


class ConflictType(StrEnum):
    CONTRADICTION = "contradiction"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    DEAD_RULE = "dead_rule"
    JURISDICTIONAL_OVERLAP = "jurisdictional_overlap"
    SUPERSESSION_CHAIN = "supersession_chain"


class Conflict(BaseModel):
    """A detected conflict between rules."""

    conflict_type: ConflictType
    rule_ids: list[str] = Field(..., min_length=1)
    description: str
    severity: str = "medium"  # low, medium, high
