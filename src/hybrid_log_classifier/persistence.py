import sqlite3
from pathlib import Path

from .domain import Classification


class ClassificationStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path, timeout=15.0) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS classifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL,
                    latency_ms REAL NOT NULL
                )
                """
            )

    def save(self, text: str, result: Classification) -> None:
        # WAL improves reader/writer coexistence; writes remain serialized by SQLite.
        # The busy timeout lets a concurrent writer wait rather than fail immediately.
        with sqlite3.connect(self._path, timeout=15.0) as connection:
            connection.execute("PRAGMA busy_timeout=15000")
            connection.execute(
                "INSERT INTO classifications(text, category, tier, confidence, reason, latency_ms) VALUES (?, ?, ?, ?, ?, ?)",
                (text, result.category.value, result.tier.value, result.confidence, result.reason, result.latency_ms),
            )
