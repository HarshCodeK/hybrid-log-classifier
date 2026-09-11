"""Offline smoke tests — no network, no heavy deps required.

Run from repo root:  python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.regex_classifier import classify_regex  # noqa: E402
from src.ml_classifier import classify_ml  # noqa: E402
from src.monitor import init_db, log_result, get_tier_counts  # noqa: E402
import src.monitor as monitor  # noqa: E402


def test_regex_catches_each_category():
    cases = {
        "Security Alert": "Multiple failed login attempts detected for user admin_42",
        "Resource Usage": "Memory usage at 87% on server node-12, threshold exceeded",
        "Workflow Error": "Task queue processing failed for job ID 8823",
        "Deprecation Warning": "Function getUserData() is deprecated, use fetchUser() instead",
    }
    for expected, line in cases.items():
        assert classify_regex(line) == expected, line


def test_regex_misses_ambiguous_line():
    assert classify_regex("User says the app feels slow today") is None


def test_ml_never_raises_even_untrained():
    # With no trained model or no sentence-transformers installed, the ML tier
    # must fall through (None, 0.0) so the pipeline can continue to tier 3.
    cat, conf = classify_ml("Cache hit ratio dropped to 34% on Redis instance")
    assert cat is None or isinstance(cat, str)
    assert isinstance(conf, float)


def test_sqlite_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "DB_PATH", str(tmp_path / "test.db"))
    init_db()
    log_result("some log", "Security Alert", "regex", 1.0, 5.5)
    log_result("other log", "Unknown", "llm", None, 800.0)
    counts = get_tier_counts()
    assert counts == {"regex": 1, "llm": 1}


def test_api_boots_and_classifies_regex_tier():
    fastapi = __import__("fastapi")
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    r = client.post("/classify", json={"text": "Disk space critical: /dev/sda1 at 92% capacity"})
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "Resource Usage"
    assert body["tier_used"] == "regex"
    assert body["latency_ms"] >= 0

    s = client.get("/stats")
    assert s.status_code == 200
    assert isinstance(s.json(), dict)
