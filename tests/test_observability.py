from hybrid_log_classifier.observability import RequestMetrics


def test_metrics_count_status_duration_and_active_requests():
    metrics = RequestMetrics()
    metrics.begin()
    metrics.finish("/classify", 200, 12.5)
    metrics.begin()
    metrics.finish("/classify", 503, 7.5)

    result = metrics.snapshot()
    assert result["requests_total"] == 2
    assert result["requests_active"] == 0
    assert result["server_errors_total"] == 1
    assert result["mean_request_duration_ms"] == 10.0
    assert result["requests_by_route"] == {"/classify": 2}
    assert result["responses_by_status"] == {"200": 1, "503": 1}
    assert result["scope"] == "this_process_only"


def test_snapshot_does_not_expose_mutable_internal_counters():
    metrics = RequestMetrics()
    metrics.finish("/health", 200, 1)
    snapshot = metrics.snapshot()
    snapshot["requests_by_route"]["/injected"] = 99
    assert "/injected" not in metrics.snapshot()["requests_by_route"]
