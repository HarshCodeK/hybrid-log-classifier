import sqlite3
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from hybrid_log_classifier.api import app, get_classifier
from hybrid_log_classifier.classifier import CATEGORIES, LogClassifier, RULES, train_model


@pytest.fixture
def classifier():
    return LogClassifier(llm_enabled=False)


@pytest.fixture
def client():
    get_classifier.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_classifier.cache_clear()


def test_model_trains_ten_categories():
    model = train_model()
    assert set(model.classes_) == set(CATEGORIES)
    assert len(model.named_steps["tfidf"].vocabulary_) > 100


@pytest.mark.parametrize("category,log", [
    ("security", "Failed login for user=alice"),
    ("availability", "Health check failed for checkout"),
    ("performance", "P95 latency spike exceeded alert limit"),
    ("resource_exhaustion", "OOMKilled: container exceeded memory limit"),
    ("database", "Database deadlock detected"),
    ("network", "DNS resolution failed for api.internal"),
    ("deployment", "Rollout failed for payments"),
    ("data_integrity", "Checksum mismatch for stored object"),
    ("configuration", "Missing environment variable PAYMENT_SECRET"),
    ("dependency_failure", "Circuit breaker opened after upstream failures"),
])
def test_each_regex_category(classifier, category, log):
    result = classifier.classify(log)
    assert result.category == category
    assert result.categories == (category,)
    assert result.tier == "regex"
    assert result.confidence == 1.0


@pytest.mark.parametrize("log,expected", [
    ("Database connection timed out; disk space is full on worker-3", ("resource_exhaustion", "database")),
    ("Failed login for alice; DNS resolution failed", ("security", "network")),
    ("Rollout failed; health check failed", ("availability", "deployment")),
    ("Checksum mismatch and database deadlock detected", ("database", "data_integrity")),
    ("Missing environment variable X; circuit breaker opened", ("configuration", "dependency_failure")),
])
def test_multiple_regex_signatures_return_all_categories(classifier, log, expected):
    result = classifier.classify(log)
    assert result.categories == expected
    assert result.category == ", ".join(expected)
    assert result.tier == "regex"


def test_duplicate_signatures_deduplicate_category(classifier):
    result = classifier.classify("Failed login; unauthorized access; failed login")
    assert result.categories == ("security",)


def test_regex_is_case_insensitive(classifier):
    assert classifier.classify("DATABASE DEADLOCK DETECTED").category == "database"


def test_empty_text_rejected(classifier):
    with pytest.raises(ValueError):
        classifier.classify("  ")


def test_regex_short_circuits_model_and_llm(classifier):
    with patch.object(classifier.model, "predict_proba", side_effect=AssertionError("ML should not run")):
        result = classifier.classify("Failed login for user=alice")
    assert result.tier == "regex"


def test_default_threshold_is_point_six(monkeypatch):
    monkeypatch.delenv("ML_CONFIDENCE_THRESHOLD", raising=False)
    assert LogClassifier(llm_enabled=False).threshold == 0.60


def test_configured_threshold_is_used(monkeypatch):
    monkeypatch.setenv("ML_CONFIDENCE_THRESHOLD", "0.75")
    assert LogClassifier(llm_enabled=False).threshold == 0.75


def test_invalid_threshold_rejected(monkeypatch):
    monkeypatch.setenv("ML_CONFIDENCE_THRESHOLD", "1.2")
    with pytest.raises(ValueError):
        LogClassifier(llm_enabled=False)


def test_ml_route_when_top_score_meets_threshold(classifier):
    model = classifier.model
    terms = model.named_steps["tfidf"].transform(["The endpoint response time became sluggish during peak traffic"])
    assert terms.nnz > 0
    probabilities = np.zeros((1, len(model.classes_)))
    probabilities[0, list(model.classes_).index("performance")] = 0.71
    with patch.object(model.named_steps["classifier"], "predict_proba", return_value=probabilities):
        result = classifier.classify("The endpoint response time became sluggish during peak traffic")
    assert result.tier == "ml"
    assert result.category == "performance"


def test_ml_below_threshold_includes_score_in_reason(monkeypatch):
    monkeypatch.setenv("ML_CONFIDENCE_THRESHOLD", "0.60")
    classifier = LogClassifier(llm_enabled=False)
    model = classifier.model
    probabilities = np.zeros((1, len(model.classes_)))
    probabilities[0, list(model.classes_).index("performance")] = 0.42
    with patch.object(model.named_steps["classifier"], "predict_proba", return_value=probabilities):
        result = classifier.classify("The endpoint response time became sluggish during peak traffic")
    assert result.tier == "llm_not_configured"
    assert "42.0%" in result.reason
    assert "60%" in result.reason


def test_ml_score_equal_to_threshold_is_accepted(monkeypatch):
    monkeypatch.setenv("ML_CONFIDENCE_THRESHOLD", "0.60")
    classifier = LogClassifier(llm_enabled=False)
    model = classifier.model
    probabilities = np.zeros((1, len(model.classes_)))
    probabilities[0, list(model.classes_).index("performance")] = 0.60
    with patch.object(model.named_steps["classifier"], "predict_proba", return_value=probabilities):
        result = classifier.classify("The endpoint response time became sluggish during peak traffic")
    assert result.tier == "ml"


def test_unknown_vocabulary_without_key_abstains(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    classifier = LogClassifier(llm_enabled=False)
    result = classifier.classify("qzxvblorf=99173 glarfnok_tesselate=0xA9")
    assert result.category == "unknown"
    assert result.tier == "llm_not_configured"


def test_groq_fallback_receives_low_confidence_log(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    classifier = LogClassifier(llm_enabled=True)
    with patch.object(classifier, "_classify_with_groq", return_value=("network", 0.82, "Network issue")) as groq:
        result = classifier.classify("qzxvblorf=99173 glarfnok_tesselate=0xA9")
    groq.assert_called_once()
    assert result.category == "network"
    assert result.tier == "llm"


def test_groq_failure_abstains(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    classifier = LogClassifier(llm_enabled=True)
    with patch.object(classifier, "_classify_with_groq", side_effect=ValueError("invalid response")):
        result = classifier.classify("qzxvblorf=99173 glarfnok_tesselate=0xA9")
    assert result.category == "unknown"
    assert result.tier == "llm_error"


def test_groq_http_failure_abstains(monkeypatch):
    import httpx
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    classifier = LogClassifier(llm_enabled=True)
    with patch.object(classifier, "_classify_with_groq", side_effect=httpx.TimeoutException("timeout")):
        result = classifier.classify("qzxvblorf=99173 glarfnok_tesselate=0xA9")
    assert result.tier == "llm_error"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_response_includes_category_array(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    response = client.post("/classify", json={"text": "Database connection timed out; disk space is full"})
    assert response.status_code == 200
    assert response.json()["categories"] == ["resource_exhaustion", "database"]


def test_api_persists_result(client, tmp_path, monkeypatch):
    db = tmp_path / "result.db"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    response = client.post("/classify", json={"text": "Database deadlock detected"})
    assert response.status_code == 200
    with sqlite3.connect(db) as connection:
        row = connection.execute("SELECT log_text, category, tier FROM classifications").fetchone()
    assert row == ("Database deadlock detected", "database", "regex")


def test_api_rejects_empty_text(client):
    assert client.post("/classify", json={"text": ""}).status_code == 422


def test_api_rejects_missing_text(client):
    assert client.post("/classify", json={}).status_code == 422


def test_api_rejects_oversized_text(client):
    assert client.post("/classify", json={"text": "x" * 20001}).status_code == 422


def test_latency_is_nonnegative(classifier):
    assert classifier.classify("Failed login for user=alice").latency_ms >= 0


def test_regex_rule_list_covers_all_categories():
    assert {category for category, _ in RULES} == set(CATEGORIES)
