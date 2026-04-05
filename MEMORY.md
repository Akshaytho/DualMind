# Shared Memory — Persistent Context Across Turns

Both minds MUST read this file every turn. Update it when you make important decisions or discover patterns.

## Architecture Decisions
- 3-layer: Ingestion → Extraction → Detection
- Flat file structure (no nested modules)
- Python + pydantic + NetworkX + SQLite

## Current Code Map
_Update this as files are added/changed:_
- workspace/rulelint/models.py — Rule schema (13 fields, pydantic)
- workspace/rulelint/detection.py — 5 conflict algorithms
- workspace/rulelint/extraction.py — LLM rule extraction via Claude tool_use
- workspace/rulelint/ingestion.py — PDF to text pipeline
- workspace/rulelint/store.py — SQLite storage
- workspace/tests/ — all tests

## Patterns & Conventions
_Add patterns here so both minds stay consistent:_

## Known Bugs & Tech Debt
_Track issues here:_

## What Worked / What Didn't
_Learn from mistakes:_
