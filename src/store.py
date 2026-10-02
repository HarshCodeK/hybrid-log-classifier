"""SQLite persistence for classification runs.

Why SQLite and not Postgres: this tool is meant to run on one engineer's laptop
against their own log files. There is no second user, no concurrency problem,
and no server to install. SQLite is a single file that ships with Python, which
means `git clone && pytest` works with nothing else installed.

If this ever needed multiple users, Postgres is the right answer -- but that is
a different product, and picking SQLite keeps this one honest.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "logs.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT NOT NULL,
    source            TEXT,
    total_lines       INTEGER NOT NULL,
    regex_count       INTEGER NOT NULL,
    ml_count          INTEGER NOT NULL,
    llm_count         INTEGER NOT NULL,
    incident_count    INTEGER NOT NULL,
    total_cost_usd    REAL    NOT NULL,
    llm_fallback      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS classifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    logged_at   TEXT NOT NULL,
    text        TEXT NOT NULL,
    timestamp   TEXT,
    category    TEXT NOT NULL,
    severity    TEXT NOT NULL,
    tier_used   TEXT NOT NULL,
    confidence  REAL,
    matched     TEXT,
    latency_ms  REAL NOT NULL,
    cost_usd    REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_classifications_run  ON classifications(run_id);
CREATE INDEX IF NOT EXISTS idx_classifications_cat  ON classifications(category);
CREATE INDEX IF NOT EXISTS idx_classifications_time ON classifications(logged_at);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection and make sure the schema exists.

    Why `check_same_thread=False`: FastAPI runs sync endpoints in a threadpool,
    so a connection created on one thread can be read on another. This is safe
    for our usage -- each request gets its own connection and SQLite serialises
    writes internally -- but it is worth knowing about if this grows.

    Why the schema is created here rather than in a migration step: two tables
    and `CREATE TABLE IF NOT EXISTS` is idempotent and self-healing. A
    migrations directory would be the right call at a dozen tables, and would be
    over-engineering at two.
    """
    conn = sqlite3.connect(db_path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create the database and tables if they are not already there."""
    _connect(db_path).close()


def save_run(summary: dict, db_path: Path | None = None) -> int:
    """Persist a completed batch run and return its id.

    The summary dict is written once, at the end, rather than updating a row
    per line. A 4,000-line batch is one insert plus one bulk insert of the
    classifications, which is dramatically faster than 4,000 individual writes
    and avoids a partially-written run if something fails halfway.
    """
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """INSERT INTO runs
               (started_at, source, total_lines, regex_count, ml_count, llm_count,
                incident_count, total_cost_usd, llm_fallback)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                summary.get("started_at") or _dt.datetime.now().isoformat(),
                summary.get("source"),
                summary["total_lines"],
                summary["tier_counts"].get("regex", 0),
                summary["tier_counts"].get("ml", 0),
                summary["tier_counts"].get("llm", 0),
                len(summary.get("incidents", [])),
                summary.get("total_cost_usd", 0.0),
                1 if summary.get("llm_fallback") else 0,
            ),
        )
        run_id = cursor.lastrowid

        rows = [
            (
                run_id,
                item.get("logged_at") or _dt.datetime.now().isoformat(),
                item["text"],
                item.get("timestamp"),
                item["category"],
                item["severity"],
                item["tier_used"],
                item.get("confidence"),
                item.get("matched"),
                item["latency_ms"],
                item.get("estimated_cost_usd", 0.0),
            )
            for item in summary.get("classifications", [])
        ]
        conn.executemany(
            """INSERT INTO classifications
               (run_id, logged_at, text, timestamp, category, severity, tier_used,
                confidence, matched, latency_ms, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def list_runs(limit: int = 20, db_path: Path | None = None) -> list[dict]:
    """Recent runs, newest first, for the history panel."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM runs ORDER BY id DESC LIMIT ?""", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_run(run_id: int, db_path: Path | None = None) -> dict | None:
    """One run plus its classifications. Used by the history drill-down."""
    conn = _connect(db_path)
    try:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return None
        rows = conn.execute(
            "SELECT * FROM classifications WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return {"run": dict(run), "classifications": [dict(r) for r in rows]}
    finally:
        conn.close()


def category_breakdown(db_path: Path | None = None) -> dict[str, int]:
    """Total classifications per category across all runs."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT category, COUNT(*) FROM classifications GROUP BY category"
        ).fetchall()
        return {row[0]: row[1] for row in rows}
    finally:
        conn.close()
