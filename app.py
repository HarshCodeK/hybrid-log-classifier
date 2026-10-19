from datetime import datetime
import csv
import json
import os
from pathlib import Path
import sys

import streamlit as st

# Make the src-layout package importable on Streamlit Community Cloud as well as locally.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hybrid_log_classifier.api import build_service
from hybrid_log_classifier.domain import LogEvent
from hybrid_log_classifier.ml import train_model
from hybrid_log_classifier.triage import TriageInputError, run_triage


st.set_page_config(page_title="Hybrid Log Classifier", page_icon="🔎", layout="wide")
st.title("Hybrid Log Classifier")
st.caption("Rules first → ML when confident → optional LLM only when needed")


@st.cache_resource
def get_service():
    model_path = Path(os.getenv("MODEL_PATH", "models/classifier.joblib"))
    if not model_path.exists():
        with (ROOT / "data" / "training.csv").open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        train_model(rows, model_path)
    return build_service()


def parse_log_lines(raw: str) -> list[LogEvent]:
    events: list[LogEvent] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        if len(events) >= 200:
            raise ValueError("At most 200 log events can be analyzed in one run.")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Line {line_number} is not valid JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"Line {line_number} must be a JSON object.")
        text = record.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
            raise ValueError(f"Line {line_number} needs non-empty text of at most 20,000 characters.")
        timestamp = record.get("timestamp")
        parsed_timestamp = None
        if timestamp is not None:
            if not isinstance(timestamp, str):
                raise ValueError(f"Line {line_number} timestamp must be an ISO-8601 string.")
            try:
                parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"Line {line_number} timestamp must be ISO-8601.") from exc
        events.append(LogEvent(text, parsed_timestamp))
    return events


tab_classify, tab_triage = st.tabs(["Classify one log", "Incident triage"])

with tab_classify:
    text = st.text_area("Log line", placeholder="failed login user=alice ip=203.0.113.7")
    if st.button("Classify", key="classify-one"):
        if not text.strip():
            st.warning("Enter a log line.")
        else:
            try:
                result = get_service().classify(LogEvent(text))
                st.metric("Category", result.category.value)
                st.write({
                    "tier": result.tier.value,
                    "confidence": round(result.confidence, 3),
                    "reason": result.reason,
                    "latency_ms": round(result.latency_ms, 2),
                })
            except (RuntimeError, ValueError, OSError) as exc:
                st.error("The classifier could not initialize or process this log.")
                st.caption(type(exc).__name__)

with tab_triage:
    st.subheader("Evidence-first incident triage")
    st.write(
        "Upload a JSON report created by scripts/load_test.py and paste timestamped "
        "logs as JSON Lines. The workflow classifies logs, groups incidents, checks "
        "the load-test window, and drafts diagnostic steps. It never runs remediation."
    )
    report_file = st.file_uploader("Load-test JSON report", type=["json"], key="triage-report")
    log_lines = st.text_area(
        "Logs (one JSON object per line)",
        placeholder='{"timestamp":"2026-10-16T12:01:00Z","text":"timeout service=checkout"}',
        height=180,
        max_chars=100_000,
        key="triage-logs",
    )
    st.caption("Bounds: report ≤ 1 MB; up to 200 log events; each log ≤ 20,000 characters.")
    if st.button("Run triage workflow", type="primary", key="run-triage"):
        if report_file is None:
            st.warning("Upload a load-test JSON report first.")
        elif len(report_file.getvalue()) > 1_000_000:
            st.error("The load-test report exceeds the 1 MB input limit.")
        else:
            try:
                report = json.loads(report_file.getvalue().decode("utf-8"))
                if not isinstance(report, dict):
                    raise ValueError("The load-test report must be a JSON object.")
                events = parse_log_lines(log_lines)
                result = run_triage(report, events, get_service().classify)
                summary = result["summary"]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Failed requests", summary["error_count"])
                c2.metric("Error rate", f'{summary["error_rate"]:.1%}')
                c3.metric("p95 latency", "n/a" if summary["p95_latency_ms"] is None else f'{summary["p95_latency_ms"]:.0f} ms')
                c4.metric("Grouped incidents", summary["incident_count"])
                st.markdown("#### Observed signals")
                if result["signals"]:
                    st.dataframe(result["signals"], use_container_width=True, hide_index=True)
                else:
                    st.info("No high-signal failure pattern was found in the supplied inputs.")
                st.markdown("#### Recommended diagnostic checks")
                st.dataframe(result["recommended_checks"], use_container_width=True, hide_index=True)
                with st.expander("Classified log events"):
                    st.dataframe(result["classified_logs"], use_container_width=True, hide_index=True)
                with st.expander("Incident groups"):
                    st.dataframe(result["incidents"], use_container_width=True, hide_index=True)
                with st.expander("Tool execution trace"):
                    st.json(result["tool_trace"])
                if result["warnings"]:
                    st.warning("Input/report caveats: " + " ".join(result["warnings"]))
                st.caption(result["safety_note"])
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TriageInputError) as exc:
                st.error(f"Triage could not run: {exc}")
            except (RuntimeError, OSError) as exc:
                st.error("The classifier could not initialize or complete triage.")
                st.caption(type(exc).__name__)
