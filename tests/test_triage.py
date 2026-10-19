from datetime import datetime, timedelta, timezone

import pytest

from hybrid_log_classifier.domain import Category, Classification, ClassificationTier, LogEvent
from hybrid_log_classifier.triage import TriageInputError, run_triage


class RuleOnlyClassifier:
    def classify(self, event: LogEvent) -> Classification:
        text = event.text.lower()
        if "timeout" in text or "unavailable" in text:
            category = Category.AVAILABILITY
        elif "latency" in text or "slow request" in text:
            category = Category.PERFORMANCE
        elif "deployment failed" in text or "rollout failed" in text:
            category = Category.DEPLOYMENT
        else:
            category = Category.UNKNOWN
        tier = ClassificationTier.RULE if category is not Category.UNKNOWN else ClassificationTier.UNKNOWN
        confidence = 1.0 if tier is ClassificationTier.RULE else 0.0
        return Classification(category, tier, confidence, "test classifier", 0.1)


def report(**overrides):
    value = {
        "timestamp_utc": "2026-10-16T12:05:00Z",
        "duration_seconds": 300,
        "requested_requests": 100,
        "success_count": 92,
        "error_count": 8,
        "error_rate": 0.08,
        "latency_ms": {"p50": 120, "p95": 1400, "p99": 2100, "max": 2600},
        "status_codes": {"200": 92, "500": 8},
        "transport_errors": {},
    }
    value.update(overrides)
    return value


def test_triage_runs_bounded_tools_and_reports_evidence():
    start = datetime(2026, 10, 16, 12, 1, tzinfo=timezone.utc)
    logs = [
        LogEvent("timeout service=checkout", start),
        LogEvent("service unavailable service=checkout", start + timedelta(seconds=30)),
    ]

    result = run_triage(report(), logs, RuleOnlyClassifier().classify)

    assert result["summary"]["error_count"] == 8
    assert result["summary"]["timestamped_events_in_load_window"] == 2
    assert result["summary"]["incident_count"] == 1
    assert {signal["id"] for signal in result["signals"]} >= {
        "request_errors", "http_5xx", "high_p95_latency"
    }
    assert result["tool_trace"][-1]["tool"] == "draft_diagnostic_checks"
    assert any("server exception logs" in check["action"] for check in result["recommended_checks"])
    assert "No commands were executed" in result["safety_note"]


def test_triage_does_not_claim_time_correlation_without_report_timestamp():
    result = run_triage(
        report(timestamp_utc=None),
        [LogEvent("timeout service=checkout")],
        RuleOnlyClassifier().classify,
    )
    assert result["summary"]["timestamped_events_in_load_window"] == 0
    assert any("correlation was unavailable" in warning for warning in result["warnings"])


def test_triage_rejects_infinite_latency():
    with pytest.raises(TriageInputError, match="finite"):
        run_triage(
            report(latency_ms={"p50": 1, "p95": float("inf")}),
            [],
            RuleOnlyClassifier().classify,
        )


def test_triage_rejects_more_than_200_events():
    events = [LogEvent("timeout service=checkout") for _ in range(201)]
    with pytest.raises(TriageInputError, match="limited to 200"):
        run_triage(report(), events, RuleOnlyClassifier().classify)


def test_triage_warns_when_report_counts_disagree():
    result = run_triage(
        report(requested_requests=100, success_count=90, error_count=5),
        [],
        RuleOnlyClassifier().classify,
    )
    assert any("does not equal requested_requests" in warning for warning in result["warnings"])



def test_out_of_window_log_is_not_used_as_correlated_evidence():
    outside_window = datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc)
    result = run_triage(
        report(),
        [LogEvent("timeout service=checkout", outside_window)],
        RuleOnlyClassifier().classify,
    )

    assert result["summary"]["timestamped_events_in_load_window"] == 0
    assert result["summary"]["in_window_categories"] == {}
    assert not any(
        check["action"] == "Check health/readiness events and connection failures around the observed window."
        for check in result["recommended_checks"]
    )
