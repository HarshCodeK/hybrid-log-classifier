"""Bounded, evidence-first triage workflow for load-test reports and logs.

The workflow uses allowlisted deterministic tools and the existing classifier. It
never executes commands, changes infrastructure, or claims root cause from a
single load-test report.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Callable

from .domain import Classification, LogEvent
from .incidents import Incident, group_incidents


MAX_LOG_EVENTS = 200
MAX_REPORT_DURATION_SECONDS = 86_400


class TriageInputError(ValueError):
    """Raised when a report cannot be safely interpreted."""


def _number(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TriageInputError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise TriageInputError(f"{field} must be finite and >= {minimum}")
    return result


def _count_map(value: Any, field: str) -> dict[str, int]:
    if not isinstance(value, dict) or len(value) > 100:
        raise TriageInputError(f"{field} must be an object with at most 100 entries")
    result: dict[str, int] = {}
    for key, count in value.items():
        if not isinstance(key, str) or len(key) > 32:
            raise TriageInputError(f"{field} keys must be short strings")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise TriageInputError(f"{field}[{key!r}] must be a non-negative integer")
        result[key] = count
    return result


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TriageInputError("timestamp_utc must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TriageInputError("timestamp_utc must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_load_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate only fields used by the triage workflow; ignore unrelated fields."""
    if not isinstance(report, dict):
        raise TriageInputError("load_report must be a JSON object")

    duration = _number(report.get("duration_seconds"), "duration_seconds", minimum=0.001)
    if duration > MAX_REPORT_DURATION_SECONDS:
        raise TriageInputError("duration_seconds exceeds the 24-hour analysis limit")

    requested = report.get("requested_requests")
    if requested is not None and (
        isinstance(requested, bool) or not isinstance(requested, int) or not 1 <= requested <= 100_000
    ):
        raise TriageInputError("requested_requests must be an integer from 1 to 100000")

    success = report.get("success_count")
    errors = report.get("error_count")
    for field, value in (("success_count", success), ("error_count", errors)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 100_000:
            raise TriageInputError(f"{field} must be an integer from 0 to 100000")

    latency = report.get("latency_ms", {})
    if not isinstance(latency, dict) or len(latency) > 10:
        raise TriageInputError("latency_ms must be an object with at most 10 entries")
    clean_latency: dict[str, float | None] = {}
    for key in ("p50", "p95", "p99", "max"):
        value = latency.get(key)
        clean_latency[key] = None if value is None else _number(value, f"latency_ms.{key}")

    status_codes = _count_map(report.get("status_codes", {}), "status_codes")
    transport_errors = _count_map(report.get("transport_errors", {}), "transport_errors")
    timestamp = _parse_timestamp(report.get("timestamp_utc"))
    if timestamp is not None:
        try:
            timestamp - timedelta(seconds=duration)
        except OverflowError as exc:
            raise TriageInputError(
                "timestamp_utc is too early to form a load window of this duration"
            ) from exc

    warnings: list[str] = []
    if requested is not None and success + errors != requested:
        warnings.append("success_count + error_count does not equal requested_requests")
    if clean_latency["p50"] is not None and clean_latency["p95"] is not None and clean_latency["p95"] < clean_latency["p50"]:
        warnings.append("reported p95 latency is below p50; verify the source report")
    if clean_latency["p95"] is not None and clean_latency["p99"] is not None and clean_latency["p99"] < clean_latency["p95"]:
        warnings.append("reported p99 latency is below p95; verify the source report")

    return {
        "timestamp_utc": timestamp,
        "duration_seconds": duration,
        "requested_requests": requested,
        "success_count": success,
        "error_count": errors,
        "error_rate": errors / max(success + errors, 1),
        "latency_ms": clean_latency,
        "status_codes": status_codes,
        "transport_errors": transport_errors,
        "warnings": warnings,
    }


def run_triage(
    load_report: dict[str, Any],
    events: list[LogEvent],
    classify_event: Callable[[LogEvent], Classification],
) -> dict[str, Any]:
    """Run a fixed, bounded sequence of allowlisted diagnostic tools."""
    if len(events) > MAX_LOG_EVENTS:
        raise TriageInputError(f"logs is limited to {MAX_LOG_EVENTS} events per triage run")

    report = validate_load_report(load_report)
    trace: list[dict[str, Any]] = [
        {
            "tool": "inspect_load_report",
            "status": "completed",
            "input_summary": "validated load-test JSON",
            "output_summary": {
                "success_count": report["success_count"],
                "error_count": report["error_count"],
                "error_rate": round(report["error_rate"], 5),
                "duration_seconds": report["duration_seconds"],
                "warnings": len(report["warnings"]),
            },
        }
    ]

    classified: list[tuple[LogEvent, Classification]] = [
        (event, classify_event(event)) for event in events
    ]
    category_counts = Counter(result.category.value for _, result in classified)
    trace.append({
        "tool": "classify_log_events",
        "status": "completed",
        "input_summary": f"{len(events)} log events",
        "output_summary": {"categories": dict(category_counts)},
    })

    # Only timestamped events may participate in temporal grouping. The generic
    # grouping helper treats missing timestamps as "now", which would fabricate
    # temporal proximity between undated and timestamped records.
    timestamped_classified = [
        (event, result) for event, result in classified if event.timestamp is not None
    ]
    undated_classified = [
        (event, result) for event, result in classified if event.timestamp is None
    ]
    incidents = group_incidents(timestamped_classified)
    incidents.extend(
        Incident(
            id=len(incidents) + index + 1,
            category=result.category.value,
            events=(event,),
        )
        for index, (event, result) in enumerate(undated_classified)
    )
    incident_summaries = []
    for incident in incidents:
        known_timestamps = [
            event.normalized_timestamp()
            for event in incident.events
            if event.timestamp is not None
        ]
        incident_summaries.append({
            "id": incident.id,
            "category": incident.category,
            "event_count": len(incident.events),
            "start_utc": min(known_timestamps).isoformat() if known_timestamps else None,
            "end_utc": max(known_timestamps).isoformat() if known_timestamps else None,
        })
    trace.append({
        "tool": "group_incidents",
        "status": "completed",
        "input_summary": f"{len(classified)} classified events",
        "output_summary": {"incident_count": len(incident_summaries)},
    })

    correlated_events: list[tuple[LogEvent, Classification]] = []
    correlation_available = False
    window_start = None
    window_end = report["timestamp_utc"]
    if window_end is not None:
        correlation_available = True
        window_start = window_end - timedelta(seconds=report["duration_seconds"])
        correlated_events = [
            (event, result)
            for event, result in classified
            if event.timestamp is not None
            and window_start <= event.normalized_timestamp() <= window_end
        ]
    correlated_count = len(correlated_events)
    window_category_counts = Counter(result.category.value for _, result in correlated_events)
    trace.append({
        "tool": "correlate_log_window",
        "status": "completed",
        "input_summary": "load-test time window and timestamped logs",
        "output_summary": {
            "correlation_available": correlation_available,
            "timestamped_events_in_window": correlated_count,
            "categories_in_window": dict(window_category_counts),
        },
    })

    signals: list[dict[str, Any]] = []
    if report["error_count"] > 0:
        signals.append({
            "id": "request_errors",
            "severity": "warning",
            "finding": f'{report["error_count"]} failed requests were reported by the load generator.',
            "evidence": {
                "error_count": report["error_count"],
                "error_rate": round(report["error_rate"], 5),
                "status_codes": report["status_codes"],
                "transport_errors": report["transport_errors"],
            },
        })
    server_errors = {
        code: count for code, count in report["status_codes"].items()
        if code.isdigit() and 500 <= int(code) <= 599 and count > 0
    }
    if server_errors:
        signals.append({
            "id": "http_5xx",
            "severity": "warning",
            "finding": "The target returned HTTP 5xx responses; this is evidence of server-reported failures, not a root-cause diagnosis.",
            "evidence": {"status_codes": server_errors},
        })
    if report["transport_errors"]:
        signals.append({
            "id": "transport_failures",
            "severity": "warning",
            "finding": "The client observed transport-level failures.",
            "evidence": {"transport_errors": report["transport_errors"]},
        })
    p95 = report["latency_ms"]["p95"]
    if p95 is not None and p95 >= 1000:
        signals.append({
            "id": "high_p95_latency",
            "severity": "investigate",
            "finding": "p95 latency is at least 1000 ms, a configurable-style demo heuristic rather than a universal service-level objective.",
            "evidence": {"p95_ms": p95, "heuristic_threshold_ms": 1000},
        })
    if report["warnings"]:
        signals.append({
            "id": "report_consistency",
            "severity": "investigate",
            "finding": "The report contains internal consistency warnings.",
            "evidence": {"warnings": report["warnings"]},
        })

    checks: list[dict[str, str]] = []
    def add_check(priority: str, action: str, rationale: str, evidence: str) -> None:
        if not any(item["action"] == action for item in checks):
            checks.append({
                "priority": priority,
                "action": action,
                "rationale": rationale,
                "evidence": evidence,
            })

    if server_errors:
        add_check(
            "P1",
            "Inspect server exception logs for the same time window and request path; compare request IDs where available.",
            "HTTP 5xx responses indicate the target failed requests but do not identify the failing component.",
            f"status_codes={server_errors}",
        )
    if report["transport_errors"]:
        add_check(
            "P1",
            "Check client timeout settings, connection-pool saturation, DNS/connect errors, and target availability.",
            "Transport errors are observed by the load generator and may occur before an application response exists.",
            f"transport_errors={report['transport_errors']}",
        )
    if report["error_count"] > 0 and not server_errors and not report["transport_errors"]:
        add_check(
            "P1",
            "Break down failed requests by HTTP status and endpoint before changing the service.",
            "The aggregate error count alone does not reveal whether failures are validation, throttling, or application errors.",
            f"error_count={report['error_count']}, status_codes={report['status_codes']}",
        )
    if p95 is not None and p95 >= 1000:
        add_check(
            "P2",
            "Repeat the same request mix against a recorded baseline and correlate p95/p99 with per-route metrics and host CPU/memory.",
            "A single p95 value cannot establish a regression or identify a bottleneck.",
            f"p95_ms={p95}",
        )
    category_actions = {
        "availability": ("P1", "Check health/readiness events and connection failures around the observed window."),
        "performance": ("P2", "Compare slow-request timestamps with route-level latency and host resource metrics."),
        "deployment": ("P1", "Check deployment/rollout history, process restarts, and configuration changes in the observed window."),
        "data": ("P1", "Inspect storage/database error context and verify whether retries or duplicate operations occurred."),
        "security": ("P2", "Review authentication/access events using approved, redacted logs; do not expose credentials or personal data."),
    }
    categories_for_checks = window_category_counts if correlation_available else category_counts
    for category, count in sorted(categories_for_checks.items()):
        if count and category in category_actions:
            priority, action = category_actions[category]
            add_check(priority, action, f"{count} log event(s) classified as {category}; classification is a heuristic, not proof of cause.", f"category_count[{category}]={count}")
    if not checks:
        add_check(
            "P3",
            "Capture a timestamped baseline report with server logs and host metrics, then rerun the same workload.",
            "The supplied evidence does not show a clear error signal; absence of a signal is not proof of health.",
            "No high-signal failure pattern found in supplied inputs",
        )

    checks.sort(key=lambda item: (item["priority"], item["action"]))
    trace.append({
        "tool": "draft_diagnostic_checks",
        "status": "completed",
        "input_summary": f"{len(signals)} observed signals and {len(incident_summaries)} grouped incidents",
        "output_summary": {"recommended_check_count": len(checks)},
    })

    event_results = [
        {
            "index": index,
            "timestamp_utc": event.normalized_timestamp().isoformat() if event.timestamp else None,
            "category": result.category.value,
            "tier": result.tier.value,
            "confidence": result.confidence,
            "reason": result.reason,
        }
        for index, (event, result) in enumerate(classified)
    ]

    return {
        "summary": {
            "requested_requests": report["requested_requests"],
            "success_count": report["success_count"],
            "error_count": report["error_count"],
            "error_rate": round(report["error_rate"], 5),
            "p95_latency_ms": p95,
            "log_event_count": len(events),
            "log_categories": dict(category_counts),
            "timestamped_events_in_load_window": correlated_count,
            "in_window_categories": dict(window_category_counts),
            "incident_count": len(incident_summaries),
        },
        "signals": signals,
        "classified_logs": event_results,
        "incidents": incident_summaries,
        "recommended_checks": checks,
        "warnings": report["warnings"] + (
            [] if correlation_available else ["load report has no timestamp_utc; time-window correlation was unavailable"]
        ),
        "tool_trace": trace,
        "safety_note": "Diagnostic suggestions only. No commands were executed and no infrastructure or production state was changed.",
    }
