"""Contract tests for the Streamlit front end.

`streamlit_app.py` is a rendering layer: it displays whatever
`classify_batch` returns. The risk is not that the UI is wrong, it is that the
UI reads a field the pipeline does not return — which shows up as a blank panel
in a demo and a stack trace in an interview.

So these tests assert the *contract*, not the rendering: every key the UI
touches must be present in the pipeline's return value.

Run:  python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline import classify_batch  # noqa: E402

SAMPLE_LINES = [
    "[2026-09-30 02:14:01] Multiple failed login attempts detected for user admin_42",
    "[2026-09-30 02:14:09] Failed login for user admin_42 from ip 203.0.113.7",
    "[2026-09-30 08:40:00] Memory usage at 94% on server node-12, threshold exceeded",
    "[2026-09-30 11:02:10] Deprecation warning: legacy_auth is deprecated",
]

# Every key streamlit_app.py reads out of the report.
UI_EXPECTED_KEYS = [
    "total_lines",
    "classifications",
    "incidents",
    "tier_counts",
    "total_cost_usd",
    "naive_llm_cost_usd",
    "cost_avoided_pct",
    "latency_ms",
]

# Every key the UI reads out of an individual incident.
UI_EXPECTED_INCIDENT_KEYS = ["severity", "category", "line_count", "entities",
                             "sample_lines"]


def _report(allow_llm=False):
    return classify_batch([(ln, None) for ln in SAMPLE_LINES], allow_llm=allow_llm)


class TestUiContract:
    def test_report_has_every_key_the_ui_reads(self):
        report = _report()
        missing = [k for k in UI_EXPECTED_KEYS if k not in report]
        assert not missing, (
            f"streamlit_app.py reads keys the pipeline never returns: {missing}"
        )

    def test_incidents_have_every_key_the_ui_reads(self):
        report = _report()
        assert report["incidents"], "sample produced no incidents to check"
        for inc in report["incidents"]:
            missing = [k for k in UI_EXPECTED_INCIDENT_KEYS if k not in inc]
            assert not missing, f"incident missing {missing}: {inc}"

    def test_latency_block_has_the_percentiles_the_ui_shows(self):
        report = _report()
        for key in ("p50", "p95"):
            assert key in report["latency_ms"], f"UI shows {key}"

    def test_tier_counts_include_a_regex_key(self):
        """The UI labels tiers as 'free' vs 'paid' by excluding 'regex'."""
        report = _report()
        assert "regex" in report["tier_counts"]

    def test_avoided_pct_is_a_number_between_0_and_100(self):
        report = _report()
        value = report["cost_avoided_pct"]
        assert isinstance(value, (int, float))
        assert 0 <= value <= 100

    def test_ui_module_imports(self):
        """Catches an import of a symbol that no longer exists."""
        import streamlit_app

        assert callable(streamlit_app.classify_batch)
        assert streamlit_app.SAMPLE


class TestNoDeadModelInUi:
    def test_streamlit_app_pins_no_retired_model(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "streamlit_app.py",
        )
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for dead in ("llama-3.3-70b-versatile", "llama-4-scout-17b-16e-instruct",
                     "qwen/qwen3.6-27b"):
            assert dead not in text, f"streamlit_app.py references retired {dead}"
