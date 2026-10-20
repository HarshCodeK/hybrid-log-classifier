from fastapi.testclient import TestClient

from hybrid_log_classifier.api import app, get_classifier
from hybrid_log_classifier.classifier import LogClassifier


def setup_module():
    get_classifier.cache_clear()


def test_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_regex_classification():
    classifier = LogClassifier(llm_enabled=False)
    result = classifier.classify("failed login user=demo")
    assert result.category == "security"
    assert result.tier == "regex"
    assert result.latency_ms >= 0


def test_unknown_without_groq():
    classifier = LogClassifier(llm_enabled=False)
    classifier.threshold = 0.999999
    result = classifier.classify("a very unusual event with arbitrary words")
    assert result.category == "unknown"
    assert result.tier == "ml_low_confidence"


def test_api_classify(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "classifications.db"))
    get_classifier.cache_clear()
    response = TestClient(app).post("/classify", json={"text": "connection refused by upstream"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"] == "availability"
    assert body["tier"] == "regex"
    assert body["latency_ms"] >= 0
    get_classifier.cache_clear()


def test_api_rejects_empty_text():
    response = TestClient(app).post("/classify", json={"text": ""})
    assert response.status_code == 422
