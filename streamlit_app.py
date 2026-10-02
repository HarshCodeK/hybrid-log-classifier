"""Streamlit front end for the incident triage console.

Why this exists alongside the FastAPI app
-----------------------------------------
The FastAPI service plus the static page in `static/` is the primary interface:
it is what a tool someone runs on their own machine should be — a real HTTP
API, an OpenAPI page, and a UI with no build step.

This app is the second front end over the *same* pipeline. It exists because
pasting a log file and reading a ranked incident list is a data-exploration
task, which is what Streamlit is good at.

It is deliberately thin. `classify_batch` already does the classification, the
tier accounting, the latency percentiles, the cost comparison and the incident
grouping, so this file only renders what it returns. Every number shown here is
computed in `src/pipeline.py`, which is where the tests live.

Run:  streamlit run streamlit_app.py
"""
from __future__ import annotations

import json
import os

import streamlit as st

from src.llm_classifier import DEFAULT_MODEL
from src.pipeline import classify_batch

ACCENT = "#1F7A5C"
INK = "#12181F"
MUTED = "#5A6673"
HAIRLINE = "#DCE3E8"

SEVERITY_COLOR = {
    "critical": "#B4232A",
    "high": "#B4690E",
    "medium": MUTED,
    "low": MUTED,
}

SAMPLE = "\n".join([
    "[2026-09-30 02:14:01] Multiple failed login attempts detected for user admin_42",
    "[2026-09-30 02:14:09] Failed login for user admin_42 from ip 203.0.113.7",
    "[2026-09-30 02:14:33] Authentication failure for user admin_42 from ip 203.0.113.7",
    "[2026-09-30 02:14:50] Access denied for user admin_42",
    "[2026-09-30 02:16:44] Failed login for user admin_42 from ip 203.0.113.9",
    "[2026-09-30 08:40:00] Memory usage at 94% on server node-12, threshold exceeded",
    "[2026-09-30 08:41:12] Memory usage at 96% on server node-12",
    "[2026-09-30 11:02:10] Deprecation warning: legacy_auth is deprecated, removed in v3",
    "[2026-09-30 11:45:22] ETL job weekly_export failed: connection reset by peer",
])

st.set_page_config(page_title="Incident Triage", layout="wide", page_icon="◈")

st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2.2rem; max-width: 1040px; }}
      h1, h2, h3, h4 {{ letter-spacing: -0.02em; color: {INK}; }}
      h1 {{ font-size: 1.6rem; margin-bottom: 0.1rem; }}
      .sub {{ color: {MUTED}; font-size: 0.9rem; margin-bottom: 1.4rem; }}
      .rule {{ height:1px; background:{HAIRLINE}; border:0; margin:1.3rem 0; }}
      .stat {{ border-left:2px solid {HAIRLINE}; padding-left:0.85rem; margin-top:0.7rem; }}
      .stat .v {{ font-size:0.98rem; font-weight:600; }}
      .stat .l {{ font-size:0.7rem; color:{MUTED}; text-transform:uppercase;
                  letter-spacing:0.06em; margin-top:0.1rem; }}
      .sev {{ font-size:0.7rem; font-weight:700; letter-spacing:0.06em;
              text-transform:uppercase; }}
      .stButton>button[kind="primary"] {{ background:{ACCENT}; border-color:{ACCENT}; }}
      .mono {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size:0.8rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Incident triage console")
st.markdown(
    '<div class="sub">Paste or upload application logs. A regex tier catches '
    "recognisable patterns for free, an ML tier handles common phrasings, and "
    "an LLM handles the rest. Lines sharing an entity inside the same time "
    "window collapse into ranked incidents.</div>",
    unsafe_allow_html=True,
)

uploaded = st.file_uploader("Upload a .log file", type=["log", "txt"],
                            label_visibility="collapsed")

if uploaded is not None:
    raw_text = uploaded.read().decode("utf-8", errors="replace")
else:
    raw_text = st.text_area("Paste logs", value=SAMPLE, height=200,
                            label_visibility="collapsed")

has_key = bool(os.environ.get("GROQ_API_KEY"))
use_llm = st.checkbox(
    "Allow the LLM tier (sends unmatched lines to Groq)",
    value=has_key,
    disabled=not has_key,
    help="Unmatched lines go to an LLM, which costs money. Off means the regex "
         "and ML tiers answer alone and anything they are unsure about comes "
         "back as Unknown.",
)
if not has_key:
    st.caption("No GROQ_API_KEY configured, so the LLM tier is unavailable.")

st.markdown('<hr class="rule">', unsafe_allow_html=True)

if st.button("Triage logs", type="primary"):
    lines = [ln for ln in (l.strip() for l in raw_text.splitlines()) if ln]
    if not lines:
        st.error("No log lines to classify.")
        st.stop()
    with st.spinner(f"Classifying {len(lines)} lines…"):
        st.session_state["report"] = classify_batch(
            [(ln, None) for ln in lines], allow_llm=bool(use_llm)
        )

report = st.session_state.get("report")

if report:
    rows = report.get("classifications", [])
    incidents = report.get("incidents", [])
    tiers = report.get("tier_counts", {})
    spent = report.get("total_cost_usd", 0.0)
    naive = report.get("naive_llm_cost_usd", 0.0)
    avoided = report.get("cost_avoided_pct", 0.0)
    lat = report.get("latency_ms", {})
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    paid = sum(v for k, v in tiers.items() if k != "regex")

    cols = st.columns(4)
    for col, value, label in [
        (cols[0], report.get("total_lines", 0), "lines"),
        (cols[1], len(incidents), "incidents"),
        (cols[2], f"{tiers.get('regex', 0)} free / {paid} paid", "tier split"),
        (cols[3], f"{avoided}%", "cost avoided"),
    ]:
        with col:
            st.markdown(
                f'<div class="stat"><div class="v">{value}</div>'
                f'<div class="l">{label}</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown(
        f'<div class="sub" style="margin-top:1rem">'
        f'p50 {lat.get("p50", 0)} ms · p95 {lat.get("p95", 0)} ms · '
        f'est. spend ${spent:.6f} of ${naive:.6f} if every line went to the LLM '
        f'· model {model}</div>',
        unsafe_allow_html=True,
    )

    st.markdown("#### Incidents")
    if not incidents:
        st.info("No incidents — nothing shared an entity inside the time window.")
    for inc in incidents:
        sev = inc.get("severity", "low")
        colour = SEVERITY_COLOR.get(sev, MUTED)
        n = inc.get("line_count", 0)
        entities = ", ".join(inc.get("entities", [])[:4]) or "no entity"
        st.markdown(
            f'<div style="border-left:3px solid {colour};padding:0.5rem 0 0.5rem 0.8rem;'
            f'margin-bottom:0.7rem">'
            f'<span class="sev" style="color:{colour}">{sev}</span> '
            f'<strong>{inc.get("category", "Unknown")}</strong> '
            f'<span class="mono" style="color:{MUTED}">· {n} line'
            f'{"s" if n != 1 else ""} · {entities}</span></div>',
            unsafe_allow_html=True,
        )
        with st.expander("Sample lines"):
            for line in inc.get("sample_lines", [])[:5]:
                st.markdown(f'<div class="mono">{line}</div>', unsafe_allow_html=True)

    with st.expander("All classifications"):
        st.dataframe([{k: v for k, v in r.items() if k != "text"} for r in rows],
                     use_container_width=True)

    st.download_button(
        "Download report (JSON)",
        data=json.dumps(report, indent=2, default=str),
        file_name="triage_report.json",
        mime="application/json",
    )
