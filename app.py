"""Streamlit front end.

Run:  streamlit run app.py
"""
import json

import streamlit as st

from src import models
from src.incidents import SEVERITY_ORDER
from src.llm_tier import available
from src.pipeline import classify_batch

ACCENT, INK, MUTED, RULE = "#1F7A5C", "#12181F", "#5A6673", "#DCE3E8"
SEV_COLOR = {"critical": "#B4232A", "high": "#B4690E", "medium": MUTED, "low": MUTED}

st.set_page_config(page_title="Incident Triage", layout="wide", page_icon="◈")
st.markdown(f"""
<style>
  .block-container {{ padding-top: 2.2rem; max-width: 1040px; }}
  h1, h2, h3 {{ letter-spacing:-0.02em; color:{INK}; }}
  h1 {{ font-size:1.6rem; margin-bottom:.1rem; }}
  .sub {{ color:{MUTED}; font-size:.9rem; margin-bottom:1.4rem; }}
  .rule {{ height:1px; background:{RULE}; border:0; margin:1.3rem 0; }}
  .stat {{ border-left:2px solid {RULE}; padding-left:.85rem; margin-top:.7rem; }}
  .stat .v {{ font-size:.98rem; font-weight:600; }}
  .stat .l {{ font-size:.7rem; color:{MUTED}; text-transform:uppercase;
              letter-spacing:.06em; margin-top:.1rem; }}
  .sev {{ font-size:.7rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }}
  .stButton>button[kind="primary"] {{ background:{ACCENT}; border-color:{ACCENT}; }}
  .mono {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.8rem; }}
</style>""", unsafe_allow_html=True)

st.title("Incident triage console")
st.markdown('<div class="sub">A regex tier catches recognisable patterns for free, '
            "an ML tier handles common phrasings, and an LLM handles the rest. "
            "Lines sharing an entity inside the same time window become incidents.</div>",
            unsafe_allow_html=True)

# model picker, from the registry
ids = list(models.MODELS)
labels = {m: models.MODELS[m][0] for m in ids}
with st.sidebar:
    st.markdown("#### LLM tier model")
    chosen = st.selectbox("model", ids, format_func=lambda m: f"{labels[m]} — {m}",
                          label_visibility="collapsed")
    st.caption(f"${models.MODELS[chosen][1]:.3f} in / ${models.MODELS[chosen][2]:.2f} out per 1M tokens")
    if not available():
        st.caption("No GROQ_API_KEY, so the LLM tier is off. Everything else still works.")

SAMPLE = """[2026-09-30 02:14:01] Multiple failed login attempts detected for user admin_42
[2026-09-30 02:14:09] Failed login for user admin_42 from ip 203.0.113.7
[2026-09-30 02:14:33] Authentication failure for user admin_42 from ip 203.0.113.7
[2026-09-30 02:14:50] Access denied for user admin_42
[2026-09-30 02:16:44] Failed login for user admin_42 from ip 203.0.113.9
[2026-09-30 08:40:00] Memory usage at 94% on server node-12, threshold exceeded
[2026-09-30 08:41:12] Memory usage at 96% on server node-12
[2026-09-30 11:02:10] Deprecation warning: legacy_auth is deprecated, removed in v3
[2026-09-30 11:45:22] ETL job weekly_export failed: connection reset by peer
[2026-09-30 12:10:00] Health check passed for node-07"""

raw = st.text_area("Logs", value=SAMPLE, height=190, label_visibility="collapsed")

if st.button("Triage", type="primary"):
    lines = [l for l in (x.strip() for x in raw.splitlines()) if l]
    if not lines:
        st.error("No log lines to classify.")
        st.stop()
    with st.spinner(f"Classifying {len(lines)} lines..."):
        st.session_state["r"] = classify_batch([(l, None) for l in lines])

r = st.session_state.get("r")
if r:
    tiers, lat = r["tier_counts"], r["latency_ms"]
    cols = st.columns(4)
    paid = sum(v for k, v in tiers.items() if k != "regex")
    for col, val, lab in [(cols[0], r["total_lines"], "lines"),
                          (cols[1], len(r["incidents"]), "incidents"),
                          (cols[2], f"{tiers.get('regex',0)} free / {paid} paid", "tier split"),
                          (cols[3], f"{r['cost_avoided_pct']}%", "cost avoided")]:
        with col:
            st.markdown(f'<div class="stat"><div class="v">{val}</div><div class="l">{lab}</div></div>',
                        unsafe_allow_html=True)
    st.markdown(f'<div class="sub" style="margin-top:1rem">p50 {lat["p50"]} ms · p95 {lat["p95"]} ms · '
                f'est. ${r["total_cost_usd"]:.6f} of ${r["naive_llm_cost_usd"]:.6f} if every line '
                f'went to the LLM</div>', unsafe_allow_html=True)

    st.markdown("#### Incidents")
    for inc in r["incidents"]:
        c = SEV_COLOR.get(inc["severity"], MUTED)
        ent = ", ".join(inc["entities"][:4]) or "no entity"
        st.markdown(f'<div style="border-left:3px solid {c};padding:.5rem 0 .5rem .8rem;margin-bottom:.7rem">'
                    f'<span class="sev" style="color:{c}">{inc["severity"]}</span> '
                    f'<strong>{inc["category"]}</strong> '
                    f'<span class="mono" style="color:{MUTED}">· {inc["line_count"]} line'
                    f'{"s" if inc["line_count"] != 1 else ""} · {ent}</span></div>',
                    unsafe_allow_html=True)
        with st.expander("Sample lines"):
            for line in inc["sample_lines"]:
                st.markdown(f'<div class="mono">{line}</div>', unsafe_allow_html=True)

    with st.expander("Every classification"):
        st.dataframe([{k: v for k, v in x.items() if k != "text"}
                      for x in r["classifications"]], use_container_width=True)
    st.download_button("Download JSON", json.dumps(r, indent=2, default=str),
                       "triage_report.json", "application/json")
