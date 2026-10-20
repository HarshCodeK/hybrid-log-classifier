import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "runtime" / "classifications.db"


def save_result(text: str, category: str, tier: str, confidence: float, latency_ms: float) -> None:
    db_path = Path(__import__("os").getenv("DATABASE_PATH", str(DEFAULT_DB)))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=10) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS classifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_text TEXT NOT NULL,
                category TEXT NOT NULL,
                tier TEXT NOT NULL,
                confidence REAL NOT NULL,
                latency_ms REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute(
            "INSERT INTO classifications (log_text, category, tier, confidence, latency_ms) VALUES (?, ?, ?, ?, ?)",
            (text, category, tier, confidence, latency_ms),
        )
        connection.commit()
