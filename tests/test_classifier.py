"""Offline tests. No network, no API key.

Run:  python -m pytest tests/ -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import models  # noqa: E402
from src.incidents import group, parse_timestamp  # noqa: E402
from src.pipeline import classify_batch, classify_one  # noqa: E402
from src.regex_tier import classify as regex_classify, extract_entities  # noqa: E402


# --------------------------------------------------------------------------
# Tier 1: regex
# --------------------------------------------------------------------------
class TestRegexTier:
    @pytest.mark.parametrize("line,expected", [
        ("Failed login for user alice from ip 10.0.0.1", "Security Alert"),
        ("Memory usage at 94% on server node-12, threshold exceeded", "Resource Usage"),
        ("Deprecation warning: legacy_auth is deprecated", "Deprecation Warning"),
        ("ETL job nightly failed: connection reset by peer", "Workflow Error"),
    ])
    def test_known_patterns(self, line, expected):
        assert regex_classify(line)[0] == expected

    def test_unmatched_line_returns_none(self):
        assert regex_classify("the sky is blue") is None

    def test_specificity_order_beats_general(self):
        # Contains both "failed" and "login"; login must win.
        assert regex_classify("failed login attempt")[0] == "Security Alert"


# --------------------------------------------------------------------------
# Entities -- what makes incidents group correctly
# --------------------------------------------------------------------------
class TestEntities:
    def test_extracts_user_and_ip(self):
        e = extract_entities("Failed login for user admin_42 from ip 203.0.113.7")
        assert "user:admin_42" in e and "ip:203.0.113.7" in e

    def test_two_spellings_of_the_same_user_match(self):
        a = extract_entities("failed login for user=alice")
        b = extract_entities("failed login for user alice")
        assert a == b

    def test_entities_are_prefixed(self):
        # A service and a user with the same name must not merge.
        assert "user:admin" in extract_entities("login for user admin")
        assert "service:admin" in extract_entities("service admin restarted")

    def test_hyphenated_hostname_is_kept_whole(self):
        # The trap: matching "node" inside "node-12" and capturing "12",
        # which would split one host's logs across separate incidents.
        e = extract_entities("Memory usage at 99% on node-12")
        assert "host:node-12" in e


# --------------------------------------------------------------------------
# Timestamps and incident grouping
# --------------------------------------------------------------------------
class TestIncidents:
    def test_parses_leading_timestamp(self):
        ts = parse_timestamp("[2026-09-30 02:14:01] something failed")
        assert ts is not None and ts.hour == 2

    def test_returns_none_without_timestamp(self):
        assert parse_timestamp("no timestamp here") is None

    def _rows(self, lines, when):
        return [{"text": t, "category": "Workflow Error", "timestamp": when, "cost": 0.0}
                for t in lines]

    def test_same_entity_near_in_time_merges(self):
        rows = self._rows(
            ["failed for user alice at 10:00:00", "failed for user alice at 10:01:00"],
            None)
        rows[0]["text"] = "[2026-09-30 10:00:00] failed for user alice"
        rows[1]["text"] = "[2026-09-30 10:01:00] failed for user alice"
        assert len(group(rows)) == 1

    def test_same_entity_distant_in_time_splits(self):
        rows = self._rows([
            "[2026-09-30 10:00:00] failed for user alice",
            "[2026-09-30 16:00:00] failed for user alice",
        ], None)
        assert len(group(rows)) == 2

    def test_different_entities_never_merge(self):
        rows = self._rows([
            "[2026-09-30 10:00:00] failed for user alice",
            "[2026-09-30 10:00:10] failed for user bob",
        ], None)
        assert len(group(rows)) == 2

    def test_incidents_sort_worst_first(self):
        rows = [
            {"text": "Memory usage at 99% on node-12", "category": "Resource Usage",
             "timestamp": None, "cost": 0.0},
            {"text": "Failed login for user admin_42 from ip 1.2.3.4",
             "category": "Security Alert", "timestamp": None, "cost": 0.0},
        ]
        result = group(rows)
        assert result[0]["severity"] == "critical"


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------
class TestPipeline:
    def test_regex_answers_for_free(self):
        row = classify_one("Failed login for user admin_42 from ip 203.0.113.7",
                           allow_llm=False)
        assert row["tier"] == "regex"
        assert row["cost"] == 0.0

    def test_free_tiers_never_cost_money(self):
        rows = classify_batch(
            [("Failed login for user a from ip 1.1.1.1", None)], allow_llm=False)
        assert rows["total_cost_usd"] == 0.0

    def test_unknown_line_does_not_crash(self):
        row = classify_one("the sky is blue", allow_llm=False)
        assert row["category"] == "Unknown"

    def test_every_row_has_latency(self):
        rows = classify_batch([("Failed login for user a", None)], allow_llm=False)
        assert "latency_ms" in rows["classifications"][0]

    def test_batch_summary_shape(self):
        r = classify_batch([("Failed login for user a from ip 1.1.1.1", None)],
                           allow_llm=False)
        for key in ("classifications", "incidents", "tier_counts", "total_cost_usd",
                    "naive_llm_cost_usd", "cost_avoided_pct", "latency_ms"):
            assert key in r, f"missing {key}"

    def test_demo_batch_produces_incidents(self):
        import json
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "data", "demo_batch.json")) as f:
            lines = json.load(f)["lines"]
        r = classify_batch([(l, None) for l in lines], allow_llm=False)
        assert len(r["incidents"]) >= 2
        assert r["incidents"][0]["severity"] == "critical"


# --------------------------------------------------------------------------
# Models: nothing retired can be pinned
# --------------------------------------------------------------------------
class TestModels:
    def test_default_is_known(self):
        assert models.resolve() in models.MODELS

    def test_unknown_model_raises(self):
        with pytest.raises(models.UnknownModel):
            models.resolve("llama-3.3-70b-versatile")

    def test_cost_scales_with_tokens(self):
        a = models.estimate_cost_usd(models.DEFAULT_MODEL, 1000, 1000)
        b = models.estimate_cost_usd(models.DEFAULT_MODEL, 2000, 2000)
        assert b == pytest.approx(a * 2)

    def test_cheaper_model_costs_less(self):
        cheap = models.estimate_cost_usd("openai/gpt-oss-20b", 1_000_000, 1_000_000)
        dear = models.estimate_cost_usd("qwen/qwen3.8-27b", 1_000_000, 1_000_000)
        assert cheap < dear

    def test_no_retired_model_in_source(self):
        retired = ("llama-3.3-70b-versatile", "llama-4-scout-17b-16e-instruct",
                   "qwen/qwen3.6-27b")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".git", "tests", "models"}]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    text = f.read()
                for dead in retired:
                    if dead in text and name != "models.py":
                        # Only allowed inside a docstring/comment explaining the fix.
                        lines = [l for l in text.splitlines() if dead in l
                                 and not l.strip().startswith("#")
                                 and '"""' not in l]
                        assert not lines, f"{name} pins retired model: {dead}"
