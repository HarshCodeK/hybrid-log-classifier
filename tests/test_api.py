from fastapi.testclient import TestClient

from hybrid_log_classifier.api import create_app
from hybrid_log_classifier.domain import Classification, ClassificationTier, Category


class FakeService:
    def classify(self, event):
        return Classification(Category.SECURITY, ClassificationTier.RULE, 1.0, "test rule", 0.2)


def test_health():
    client = TestClient(create_app(FakeService()))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_and_process_metrics():
    client = TestClient(create_app(FakeService()))
    assert client.get("/ready").json() == {"status": "ready"}
    response = client.post("/classify", json={"text": "failed login"})
    assert response.status_code == 200
    metrics = client.get("/metrics").json()
    route = metrics["routes"]["POST /classify"]
    assert route["requests_since_start"] == 1
    assert route["status_codes_since_start"] == {"200": 1}
    assert route["latency_window_ms"]["p95"] is not None


def test_classify_contract():
    client = TestClient(create_app(FakeService()))
    response = client.post("/classify", json={"text": "failed login"})
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "security"
    assert body["tier"] == "rule"


def test_classify_rejects_empty_text():
    client = TestClient(create_app(FakeService()))
    response = client.post("/classify", json={"text": ""})
    assert response.status_code == 422


def test_unmatched_paths_do_not_create_unbounded_metric_labels():
    client = TestClient(create_app(FakeService()))
    client.get("/unmatched-a")
    client.get("/unmatched-b")
    routes = client.get("/metrics").json()["routes"]
    assert "GET <unmatched>" in routes
    assert "GET /unmatched-a" not in routes
    assert "GET /unmatched-b" not in routes


def test_llm_enabled_demo_has_shared_request_limit(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("LLM_REQUESTS_PER_MINUTE", "1")
    client = TestClient(create_app(FakeService()))

    first = client.post("/classify", json={"text": "failed login"})
    second = client.post("/classify", json={"text": "failed login"})

    assert first.status_code == 200
    assert second.status_code == 429
    metrics = client.get("/metrics").json()
    assert metrics["routes"]["POST /classify"]["status_codes_since_start"] == {"200": 1, "429": 1}
