import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs.db")


def _get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            log_text TEXT,
            category TEXT,
            tier_used TEXT,
            confidence REAL,
            latency_ms REAL
        )
    """)
    conn.commit()
    conn.close()


def log_result(log_text, category, tier_used, confidence, latency_ms):
    import datetime
    conn = _get_conn()
    conn.execute(
        "INSERT INTO logs (timestamp, log_text, category, tier_used, confidence, latency_ms) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.datetime.now().isoformat(), log_text, category, tier_used, confidence, latency_ms),
    )
    conn.commit()
    conn.close()


def get_tier_counts():
    conn = _get_conn()
    rows = conn.execute("SELECT tier_used, COUNT(*) FROM logs GROUP BY tier_used").fetchall()
    conn.close()
    return dict(rows)
