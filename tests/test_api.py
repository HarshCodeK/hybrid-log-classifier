from fastapi.testclient import TestClient

from hybrid_log_classifier.api import create_app
from hybrid_log_classifier.domain import Classification, ClassificationTier, Category


class FakeService:
    def classify(self, event):
        return Classification(Category.SECURITY, ClassificationTier.RULE, 1.0, "test rule", 0.2)


def test_health() -> None:
    client = TestClient(create_app(FakeService()))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_classify_contract() -> None:
    client = TestClient(create_app(FakeService()))
    response = client.post("/classify", json={"text": "failed login"})
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "security"
    assert body["tier"] == "rule"


def test_classify_rejects_empty_text() -> None:
    client = TestClient(create_app(FakeService()))
    response = client.post("/classify", json={"text": ""})
    assert response.status_code == 422


def test_metrics_endpoint_tracks_requests_and_timing_header():
    client = TestClient(create_app(FakeService()))
    response = client.get("/health")
    assert response.status_code == 200
    assert float(response.headers["X-Process-Time-Ms"]) >= 0
    metrics = client.get("/metrics").json()
    assert metrics["scope"] == "this_process_only"
    assert metrics["requests_total"] == 1
    assert metrics["requests_by_route"] == {"/health": 1}
    assert metrics["responses_by_status"] == {"200": 1}
