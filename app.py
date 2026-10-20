import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hybrid_log_classifier.classifier import LogClassifier
from hybrid_log_classifier.persistence import save_result

st.set_page_config(page_title="Hybrid Log Classifier", page_icon="🔎")
st.title("Hybrid Log Classifier")
st.caption("Regex → scikit-learn ML → optional Groq LLM")

@st.cache_resource
def get_classifier() -> LogClassifier:
    return LogClassifier()

log_text = st.text_area("Paste an application log", placeholder="failed login user=demo")
if st.button("Classify log", type="primary"):
    if not log_text.strip():
        st.warning("Enter a log line first.")
    else:
        try:
            result = get_classifier().classify(log_text)
            save_result(log_text, result.category, result.tier, result.confidence, result.latency_ms)
            st.subheader(result.category.upper())
            col1, col2, col3 = st.columns(3)
            col1.metric("Classification tier", result.tier)
            col2.metric("Confidence", f"{result.confidence:.1%}")
            col3.metric("Latency", f"{result.latency_ms:.2f} ms")
            st.write(result.reason)
        except Exception as exc:
            st.error("Classification failed.")
            st.caption(f"{type(exc).__name__}: {exc}")
