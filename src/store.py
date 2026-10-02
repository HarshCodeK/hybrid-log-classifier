"""Keep a history of triage runs in SQLite.

Plain sqlite3 rather than an ORM: one table, six columns, and the stdlib is
already installed. An ORM here would be a dependency with nothing to do.
"""
import json
import os
import sqlite3

from .config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    ran_at TEXT DEFAULT (datetime('now')),
    total_lines INTEGER,
    incidents INTEGER,
    cost_avoided_pct REAL,
    tiers TEXT,
    summary TEXT
)
"""


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with _conn() as c:
        c.execute(_SCHEMA)


def save(summary: dict):
    """Store one triage run."""
    init()
    with _conn() as c:
        c.execute(
            "INSERT INTO runs (total_lines, incidents, cost_avoided_pct, tiers, summary)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                summary.get("total_lines", 0),
                len(summary.get("incidents", [])),
                summary.get("cost_avoided_pct", 0.0),
                json.dumps(summary.get("tier_counts", {})),
                json.dumps(summary.get("incidents", []), default=str),
            ),
        )


def recent(limit: int = 10):
    """Most recent runs, newest first."""
    init()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
