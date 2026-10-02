"""Collapse classified lines into incidents.

Classifying 4,000 lines gives 4,000 rows, and nobody reads 4,000 rows at 2am.
What a person needs is "six incidents, two critical, start here".

The rule: two lines are the same incident when they share at least one entity
AND fall inside the same time window. Both halves matter -- sharing an entity
with no time bound merges every timeout for db-01 across a week into one
endless incident, and a time bound with no shared entity merges unrelated
errors that merely happened together.
"""
from datetime import datetime

from .config import INCIDENT_WINDOW_SECONDS
from .regex_tier import SEVERITY, extract_entities

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def parse_timestamp(text: str):
    """Pull a leading [YYYY-MM-DD HH:MM:SS] out of a line, if present."""
    if not text.startswith("["):
        return None
    end = text.find("]")
    if end == -1:
        return None
    try:
        return datetime.strptime(text[1:end], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def group(classified: list) -> list:
    """`classified` is a list of dicts with text, category, timestamp, cost.

    Returns incidents sorted worst-first.
    """
    buckets = []

    for item in classified:
        entities = extract_entities(item["text"])
        when = item.get("timestamp") or parse_timestamp(item["text"])

        target = None
        for b in buckets:
            if entities & b["entities"]:
                if when and b["last_seen"]:
                    gap = abs((when - b["last_seen"]).total_seconds())
                    if gap <= INCIDENT_WINDOW_SECONDS:
                        target = b
                        break
                elif not when or not b["last_seen"]:
                    target = b
                    break

        if target is None:
            buckets.append({
                "category": item["category"],
                "severity": SEVERITY.get(item["category"], "low"),
                "entities": set(entities),
                "lines": [item["text"]],
                "first_seen": when,
                "last_seen": when,
                "cost": item.get("cost", 0.0),
            })
        else:
            target["entities"] |= entities
            target["lines"].append(item["text"])
            target["cost"] += item.get("cost", 0.0)
            if when:
                target["first_seen"] = min(filter(None, [target["first_seen"], when]))
                target["last_seen"] = max(filter(None, [target["last_seen"], when]))

    for b in buckets:
        b["entities"] = sorted(b["entities"])
        b["line_count"] = len(b["lines"])
        b["sample_lines"] = b["lines"][:3]
        span = None
        if b["first_seen"] and b["last_seen"]:
            span = int((b["last_seen"] - b["first_seen"]).total_seconds())
        b["duration_seconds"] = span
        del b["lines"]

    return sorted(buckets, key=lambda b: (SEVERITY_ORDER[b["severity"]], -b["line_count"]))
