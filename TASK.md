# TASK: RuleLint — Regulation Conflict Detector for Indian Cities

A tool that ingests government regulation documents, parses them into structured rules, maps dependencies, and detects contradictions, circular dependencies, dead rules, and jurisdictional overlaps.

## MVP Scope
- One city: Hyderabad (GHMC + HMDA)
- One domain: building permits
- English-only PDFs
- CLI output first, web UI later

## Tech Stack (Agreed)
Python, pydantic, NetworkX, SQLite, Claude API (tool_use), FastAPI, pytest

## Architecture (Agreed)
- Layer 1: PDF → clean text (pdfplumber, Tesseract for OCR)
- Layer 2: LLM extraction → structured rules (Claude tool_use)
- Layer 3: Graph-based conflict detection (deterministic algorithms)

## Current Progress (~40%)
- Layer 1 (Ingestion): Built, needs real PDFs
- Layer 2 (Extraction): Tool schema + parser built, needs API integration
- Layer 3 (Detection): 5 algorithms, 0 false positives on ground truth
- 15 hand-extracted rules, 53 tests passing
- Missing: CLI entry point, end-to-end integration test

## Previous code from v1 repo is available for reference. Rebuild the workspace.
