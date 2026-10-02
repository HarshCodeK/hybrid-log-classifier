"""Route a line through the tiers, then summarise a batch.

This is the whole system in one file, because the routing is the idea and it
should be readable in one sitting:

    line -> regex  (free, ~0.02ms)  matched? done
         -> ML     (free, ~1ms)     confident enough? done
         -> LLM    (~$0.00003, ~200ms) done
"""
import time

from . import models
from .incidents import group
from .llm_tier import available, classify as llm_classify
from .ml_tier import classify as ml_classify
from .regex_tier import SEVERITY, classify as regex_classify

VALID = set(SEVERITY)


def classify_one(text: str, allow_llm: bool = True) -> dict:
    """Classify a single line, recording which tier answered and what it cost."""
    t0 = time.time()
    row = {"text": text, "category": None, "tier": None, "confidence": None,
           "matched": None, "cost": 0.0}

    hit = regex_classify(text)
    if hit:
        row.update(category=hit[0], tier="regex", matched=hit[2], confidence=1.0)
        row["latency_ms"] = round((time.time() - t0) * 1000, 3)
        return row

    category, confidence = ml_classify(text)
    row["confidence"] = confidence
    if category:
        row.update(category=category, tier="ml")
        row["latency_ms"] = round((time.time() - t0) * 1000, 3)
        return row

    if allow_llm and available():
        result, cost = llm_classify(text)
        if isinstance(result, str) and result in VALID:
            row.update(category=result, tier="llm", cost=cost)
            row["latency_ms"] = round((time.time() - t0) * 1000, 3)
            return row
        row["llm_note"] = str(cost)

    row.update(category="Unknown", tier="none")
    row["latency_ms"] = round((time.time() - t0) * 1000, 3)
    return row


def classify_batch(lines: list, allow_llm: bool = True) -> dict:
    """Classify many lines and summarise the result."""
    started = time.time()
    rows = []
    for text, timestamp in lines:
        row = classify_one(text, allow_llm=allow_llm)
        row["timestamp"] = timestamp
        rows.append(row)

    tier_counts = {}
    for r in rows:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1

    spent = sum(r["cost"] for r in rows)
    naive = sum(
        models.estimate_cost_usd(models.DEFAULT_MODEL, 120, 15) for _ in rows
    )
    latencies = sorted(r["latency_ms"] for r in rows) if rows else []

    def pct(p):
        if not latencies:
            return 0
        return round(latencies[min(len(latencies) - 1, int(len(latencies) * p))], 3)

    return {
        "classifications": rows,
        "incidents": group(rows),
        "tier_counts": tier_counts,
        "total_lines": len(rows),
        "total_cost_usd": round(spent, 6),
        "naive_llm_cost_usd": round(naive, 6),
        "cost_avoided_pct": round((1 - spent / naive) * 100, 2) if naive else 0.0,
        "latency_ms": {"p50": pct(0.50), "p95": pct(0.95)},
        "elapsed_ms": round((time.time() - started) * 1000),
    }
