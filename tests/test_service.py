from pathlib import Path

from hybrid_log_classifier.domain import ClassificationTier, LogEvent
from hybrid_log_classifier.ml import MLClassifier, train_model
from hybrid_log_classifier.persistence import ClassificationStore
from hybrid_log_classifier.service import ClassifierService


def build_service(tmp_path: Path, threshold: float = 0.30) -> ClassifierService:
    rows = [
        {"text": "login failed", "category": "security"},
        {"text": "unauthorized user", "category": "security"},
        {"text": "cpu high", "category": "performance"},
        {"text": "latency high", "category": "performance"},
        {"text": "compute pressure is elevated", "category": "performance"},
        {"text": "service unavailable", "category": "availability"},
        {"text": "timeout upstream", "category": "availability"},
        {"text": "deployment failed", "category": "deployment"},
        {"text": "container restart", "category": "deployment"},
        {"text": "duplicate key", "category": "data"},
        {"text": "checksum mismatch", "category": "data"},
    ]
    model_path = tmp_path / "model.joblib"
    train_model(rows, model_path)
    return ClassifierService(MLClassifier.load(model_path, threshold=threshold), ClassificationStore(tmp_path / "classifications.db"))


def test_rule_wins_before_ml(tmp_path: Path) -> None:
    result = build_service(tmp_path).classify(LogEvent("failed login user=alice"))
    assert result.tier is ClassificationTier.RULE


def test_ml_handles_semantic_variant(tmp_path: Path) -> None:
    result = build_service(tmp_path, threshold=0.40).classify(LogEvent("compute pressure is elevated"))
    assert result.tier is ClassificationTier.ML


def test_abstention_is_visible(tmp_path: Path) -> None:
    result = build_service(tmp_path, threshold=0.9999).classify(LogEvent("something unrelated"))
    assert result.tier is ClassificationTier.UNKNOWN
    assert result.reason.startswith("local model abstained")


def test_llm_escalation_limit_is_enforced_outside_the_http_api(monkeypatch) -> None:
    from types import SimpleNamespace
    from hybrid_log_classifier import service as service_module
    from hybrid_log_classifier.domain import Category

    class AbstainingML:
        def predict(self, text):
            return None, 0.2

    class CountingLLM:
        calls = 0
        def classify(self, text):
            self.calls += 1
            return SimpleNamespace(category=Category.SECURITY, confidence=0.9, reason='test provider result')

    monkeypatch.setenv('LLM_REQUESTS_PER_MINUTE', '1')
    with service_module._LLM_HITS_LOCK:
        service_module._LLM_HITS.clear()
    llm = CountingLLM()
    service = ClassifierService(AbstainingML(), llm=llm)
    first = service.classify(LogEvent('ambiguous checkout signal'))
    second = service.classify(LogEvent('another ambiguous checkout signal'))
    assert first.tier is ClassificationTier.LLM
    assert second.tier is ClassificationTier.UNKNOWN
    assert 'no provider request was made' in second.reason
    assert llm.calls == 1
