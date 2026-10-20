from unittest.mock import patch

from fastapi.testclient import TestClient

from hybrid_log_classifier.api import app, get_classifier
from hybrid_log_classifier.classifier import CATEGORIES, LogClassifier, train_model


def setup_module():
    get_classifier.cache_clear()


def test_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_model_is_really_trained_on_all_ten_categories():
    model = train_model()
    assert set(model.classes_) == set(CATEGORIES)
    assert len(model.named_steps["tfidf"].vocabulary_) > 100


def test_regex_classification_bypasses_ml_and_llm():
    classifier = LogClassifier(llm_enabled=False)
    result = classifier.classify("Failed login for user=demo")
    assert result.category == "security"
    assert result.tier == "regex"
    assert "ML and LLM were skipped" in result.reason
    assert result.latency_ms >= 0


def test_regex_rules_cover_all_ten_categories():
    classifier = LogClassifier(llm_enabled=False)
    prompts = {
        "security": "Failed login for user=alice",
        "availability": "Health check failed for checkout",
        "performance": "P95 latency spike exceeded alert limit",
        "resource_exhaustion": "OOMKilled: container exceeded memory limit",
        "database": "Database deadlock detected",
        "network": "DNS resolution failed for api.internal",
        "deployment": "Rollout failed for payments",
        "data_integrity": "Checksum mismatch for stored object",
        "configuration": "Missing environment variable PAYMENT_SECRET",
        "dependency_failure": "Circuit breaker opened after upstream failures",
    }
    assert set(prompts) == set(CATEGORIES)
    for expected, prompt in prompts.items():
        result = classifier.classify(prompt)
        assert result.category == expected, (prompt, result)
        assert result.tier == "regex", (prompt, result)


def test_ml_route_for_unmatched_but_in_vocabulary_text():
    model = train_model()
    classifier = LogClassifier(model=model, llm_enabled=False)
    performance_index = list(model.classes_).index("performance")
    probabilities = [0.01] * len(CATEGORIES)
    probabilities[performance_index] = 0.91
    # Keep this a deterministic routing test; model training is tested separately above.
    with patch.object(model.named_steps["classifier"], "predict_proba", return_value=[probabilities]):
        result = classifier.classify("The endpoint response time became sluggish during peak traffic")
    assert result.tier == "ml"
    assert result.category == "performance"


def test_low_evidence_without_key_abstains_honestly(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    classifier = LogClassifier(llm_enabled=False)
    result = classifier.classify("qzxvblorf=99173 glarfnok_tesselate=0xA9")
    assert result.category == "unknown"
    assert result.tier == "llm_not_configured"
    assert "not configured" in result.reason


def test_low_evidence_calls_groq_when_configured(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    classifier = LogClassifier(llm_enabled=True)
    with patch.object(classifier, "_classify_with_groq", return_value=("network", 0.82, "LLM test response")) as groq:
        result = classifier.classify("qzxvblorf=99173 glarfnok_tesselate=0xA9")
    groq.assert_called_once()
    assert result.category == "network"
    assert result.tier == "llm"
    assert result.confidence == 0.82


def test_groq_failure_returns_unknown(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    classifier = LogClassifier(llm_enabled=True)
    with patch.object(classifier, "_classify_with_groq", side_effect=ValueError("bad response")):
        result = classifier.classify("qzxvblorf=99173 glarfnok_tesselate=0xA9")
    assert result.category == "unknown"
    assert result.tier == "llm_error"


def test_api_classify(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "classifications.db"))
    get_classifier.cache_clear()
    response = TestClient(app).post("/classify", json={"text": "Database deadlock detected"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"] == "database"
    assert body["tier"] == "regex"
    assert body["latency_ms"] >= 0
    get_classifier.cache_clear()


def test_api_rejects_empty_text():
    response = TestClient(app).post("/classify", json={"text": ""})
    assert response.status_code == 422
