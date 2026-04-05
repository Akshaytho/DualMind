"""SQLite persistence for rules and conflicts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Conflict, ConflictType, Rule

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
    rule_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    source_file TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conflict_type TEXT NOT NULL,
    rule_ids TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class RuleStore:
    """SQLite-backed store for rules and conflicts. One class, simple CRUD."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ── Rules ────────────────────────────────────────────────────────────

    def save_rule(self, rule: Rule, source_file: str | None = None) -> None:
        """Insert or replace a single rule."""
        self._conn.execute(
            "INSERT OR REPLACE INTO rules (rule_id, data, source_file) VALUES (?, ?, ?)",
            (rule.rule_id, rule.model_dump_json(), source_file),
        )
        self._conn.commit()

    def save_rules(self, rules: list[Rule], source_file: str | None = None) -> int:
        """Bulk insert rules. Returns count saved."""
        self._conn.executemany(
            "INSERT OR REPLACE INTO rules (rule_id, data, source_file) VALUES (?, ?, ?)",
            [(r.rule_id, r.model_dump_json(), source_file) for r in rules],
        )
        self._conn.commit()
        return len(rules)

    def get_rule(self, rule_id: str) -> Rule | None:
        """Fetch a single rule by ID."""
        row = self._conn.execute("SELECT data FROM rules WHERE rule_id = ?", (rule_id,)).fetchone()
        if row is None:
            return None
        return Rule.model_validate_json(row["data"])

    def get_all_rules(self) -> list[Rule]:
        """Fetch all rules."""
        rows = self._conn.execute("SELECT data FROM rules ORDER BY rule_id").fetchall()
        return [Rule.model_validate_json(row["data"]) for row in rows]

    def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule. Returns True if it existed."""
        cursor = self._conn.execute("DELETE FROM rules WHERE rule_id = ?", (rule_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def rule_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM rules").fetchone()
        return row["cnt"]

    # ── Conflicts ────────────────────────────────────────────────────────

    def save_conflicts(self, conflicts: list[Conflict]) -> int:
        """Bulk insert conflicts. Clears existing conflicts first (re-detection)."""
        self._conn.execute("DELETE FROM conflicts")
        self._conn.executemany(
            "INSERT INTO conflicts (conflict_type, rule_ids, description, severity) VALUES (?, ?, ?, ?)",
            [
                (c.conflict_type, json.dumps(c.rule_ids), c.description, c.severity)
                for c in conflicts
            ],
        )
        self._conn.commit()
        return len(conflicts)

    def get_conflicts(self, conflict_type: ConflictType | None = None) -> list[Conflict]:
        """Fetch conflicts, optionally filtered by type."""
        if conflict_type:
            rows = self._conn.execute(
                "SELECT conflict_type, rule_ids, description, severity FROM conflicts WHERE conflict_type = ?",
                (conflict_type,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT conflict_type, rule_ids, description, severity FROM conflicts"
            ).fetchall()

        return [
            Conflict(
                conflict_type=ConflictType(row["conflict_type"]),
                rule_ids=json.loads(row["rule_ids"]),
                description=row["description"],
                severity=row["severity"],
            )
            for row in rows
        ]

    def conflict_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM conflicts").fetchone()
        return row["cnt"]
