"""Tests for the incident grouping logic.

Grouping is the part of this project that is not regex and not a model, so it
is the part most worth testing properly. The cases below are the ones that
actually broke during development:

- `node-12` was captured as `12`, splitting one host's lines into two incidents
- the 6-hour-gap case merged two genuinely separate problems into one incident
- an empty or missing timestamp did not crash the batch
"""

from __future__ import annotations

import pytest

from src.config import (
    DEPRECATION_WARNING,
    RESOURCE_USAGE,
    SECURITY_ALERT,
    UNKNOWN,
    WORKFLOW_ERROR,
)
from src.incidents import extract_entities, group_into_incidents, parse_timestamp


# --------------------------------------------------------------------------
# Entity extraction
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Out of memory error in worker on node-12", {"host:node-12"}),
        ("Memory usage at 94% on server node-12", {"host:node-12"}),
        ("Failed login for user admin_42 from ip 203.0.113.7",
         {"user:admin_42", "ip:203.0.113.7"}),
        ("Health check passed for service api-gateway", {"service:api-gateway"}),
        ("Nothing identifiable in this line", set()),
    ],
)
def test_extract_entities(text, expected):
    """Entities must be captured whole, including embedded hyphens.

    The `node-12` case is the regression guard: a naive pattern captures `12`
    and splits one host's logs across two incidents.
    """
    assert extract_entities(text) == expected


def test_distinct_hosts_do_not_merge():
    """Two different hosts are two different incidents, even on the same line."""
    a = extract_entities("CPU utilization at 95% on node-12")
    b = extract_entities("CPU utilization at 95% on node-13")
    assert a != b


def test_same_host_different_phrase_still_matches():
    """Host extraction must be stable across the phrasings logs actually use."""
    variants = [
        "Memory usage at 94% on server node-12",
        "Out of memory error in worker on node-12",
        "Disk space critical on node-12",
    ]
    assert all(extract_entities(v) == {"host:node-12"} for v in variants)


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,should_parse",
    [
        ("2026-09-30 02:14:01", True),
        ("2026-09-30T02:14:01Z", True),
        ("2026-09-30 02:14:01.123456", True),
        ("not a timestamp", False),
        ("", False),
        (None, False),
    ],
)
def test_parse_timestamp(raw, should_parse):
    result = parse_timestamp(raw)
    assert (result is not None) == should_parse


def test_missing_timestamp_does_not_crash():
    """A batch with no timestamps must still group, just without time bounds."""
    rows = [
        {"text": "Failed login for user admin_42", "category": SECURITY_ALERT,
         "severity": "critical", "timestamp": None, "estimated_cost_usd": 0.0},
        {"text": "Failed login for user admin_42", "category": SECURITY_ALERT,
         "severity": "critical", "timestamp": None, "estimated_cost_usd": 0.0},
    ]
    incidents = group_into_incidents(rows)
    assert len(incidents) == 1
    assert incidents[0]["line_count"] == 2
    assert incidents[0]["duration_seconds"] is None


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------

def _row(text, category, severity, ts, cost=0.0):
    return {"text": text, "category": category, "severity": severity,
            "timestamp": ts, "estimated_cost_usd": cost}


def test_same_entity_same_window_merges():
    """A burst of failures on one user is one incident, not five."""
    rows = [
        _row("Failed login for user admin_42", SECURITY_ALERT, "critical", "2026-09-30 02:14:01"),
        _row("Authentication failure for user admin_42", SECURITY_ALERT, "critical", "2026-09-30 02:14:09"),
        _row("Access denied for user admin_42", SECURITY_ALERT, "critical", "2026-09-30 02:14:33"),
    ]
    incidents = group_into_incidents(rows)
    assert len(incidents) == 1
    assert incidents[0]["line_count"] == 3
    assert incidents[0]["severity"] == "critical"
    # A merged incident must report the span it covers.
    assert incidents[0]["duration_seconds"] == 32


def test_same_entity_distant_in_time_splits():
    """The core rule: a shared entity is not enough, the window must also hold.

    Same user, six hours apart. These are two separate incidents -- the first
    was presumably handled, and a night-time brute force and a morning password
    problem are not the same thing.
    """
    rows = [
        _row("Failed login for user admin_42", SECURITY_ALERT, "critical", "2026-09-30 02:14:01"),
        _row("Failed login for user admin_42", SECURITY_ALERT, "critical", "2026-09-30 08:14:01"),
    ]
    incidents = group_into_incidents(rows)
    assert len(incidents) == 2


def test_different_entities_never_merge():
    """Two different users failing at the same moment are two incidents."""
    rows = [
        _row("Failed login for user alice", SECURITY_ALERT, "critical", "2026-09-30 02:14:01"),
        _row("Failed login for user kiran", SECURITY_ALERT, "critical", "2026-09-30 02:14:02"),
    ]
    assert len(group_into_incidents(rows)) == 2


def test_bucket_takes_the_worst_severity_present():
    """An incident containing a high-severity line is reported as high.

    This matters because the UI sorts by severity. A bucket that reported its
    most common severity would let a critical incident hide behind routine
    deprecation notices.

    Both lines share `user:bob` and sit inside the window, so they are one
    incident by the entity+window rule. An earlier version of this test used two
    different entities and asserted they merged -- that expectation was wrong,
    and the implementation was right to keep them apart.
    """
    rows = [
        _row("Function getUserData() is deprecated, user bob", DEPRECATION_WARNING,
             "low", "2026-09-30 02:14:01"),
        _row("Task queue processing failed for user bob", WORKFLOW_ERROR, "high",
             "2026-09-30 02:14:05"),
    ]
    incidents = group_into_incidents(rows)
    assert len(incidents) == 1
    assert incidents[0]["severity"] == "high"


def test_incidents_sort_worst_first():
    """Severity is the primary sort key, so the worst thing is on top."""
    rows = [
        _row("Function getUserData() is deprecated, use fetchUser()",
             DEPRECATION_WARNING, "low", "2026-09-30 02:14:01"),
        _row("Failed login for user alice", SECURITY_ALERT, "critical",
             "2026-09-30 02:20:01"),
        _row("Health check passed for service api-gateway", UNKNOWN, "info",
             "2026-09-30 02:25:01"),
    ]
    incidents = group_into_incidents(rows)
    assert [i["severity"] for i in incidents] == ["critical", "low", "info"]


def test_lines_without_entities_group_by_category():
    """Undated, entity-less routine lines still give the operator a count.

    Both lines are chosen to carry no recognisable entity, so they fall back to
    category-based grouping rather than forming one incident each.
    """
    rows = [
        _row("Request served from cache in 12ms", UNKNOWN, "info", None),
        _row("Quarterly report generated", UNKNOWN, "info", None),
    ]
    assert extract_entities("Request served from cache in 12ms") == set()

    incidents = group_into_incidents(rows)
    assert len(incidents) == 1
    assert incidents[0]["line_count"] == 2


def test_cost_accumulates_per_incident():
    """LLM spend must be attributable to the incident that caused it.

    This is what makes per-incident cost possible in the report -- an operator
    needs to know not just which incident is worst, but which one is expensive.
    """
    rows = [
        _row("Unfamiliar wording one", UNKNOWN, "info", "2026-09-30 02:14:01", cost=0.00002),
        _row("Unfamiliar wording two", UNKNOWN, "info", "2026-09-30 02:14:05", cost=0.00003),
    ]
    incidents = group_into_incidents(rows)
    assert incidents[0]["estimated_cost_usd"] == pytest.approx(0.00005)


def test_empty_input_returns_no_incidents():
    """An empty batch is valid and must not raise."""
    assert group_into_incidents([]) == []
