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


def test_public_classify_has_a_shared_limit_without_provider_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("API_REQUESTS_PER_MINUTE", "1")
    client = TestClient(create_app(FakeService()))

    assert client.post("/classify", json={"text": "failed login"}).status_code == 200
    assert client.post("/classify", json={"text": "failed login"}).status_code == 429



def test_triage_endpoint_runs_bounded_workflow():
    client = TestClient(create_app(FakeService()))
    response = client.post("/triage", json={
        "load_report": {
            "timestamp_utc": "2026-10-16T12:05:00Z",
            "duration_seconds": 300,
            "requested_requests": 10,
            "success_count": 8,
            "error_count": 2,
            "latency_ms": {"p50": 120, "p95": 1200, "p99": 1500, "max": 1700},
            "status_codes": {"200": 8, "500": 2},
            "transport_errors": {},
        },
        "logs": [
            {"timestamp": "2026-10-16T12:01:00Z", "text": "failed login user=demo"},
        ],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error_count"] == 2
    assert body["summary"]["timestamped_events_in_load_window"] == 1
    assert body["tool_trace"][0]["tool"] == "inspect_load_report"


def test_triage_endpoint_rejects_invalid_report():
    client = TestClient(create_app(FakeService()))
    response = client.post("/triage", json={
        "load_report": {"duration_seconds": float("inf")},
        "logs": [],
    })
    assert response.status_code == 422


def test_triage_endpoint_rejects_more_than_200_logs():
    client = TestClient(create_app(FakeService()))
    response = client.post("/triage", json={
        "load_report": {
            "duration_seconds": 10,
            "success_count": 1,
            "error_count": 0,
            "latency_ms": {},
            "status_codes": {},
            "transport_errors": {},
        },
        "logs": [{"text": "timeout"}] * 201,
    })
    assert response.status_code == 422
