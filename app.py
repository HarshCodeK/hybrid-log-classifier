import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hybrid_log_classifier.classifier import CATEGORIES, LogClassifier
from hybrid_log_classifier.persistence import save_result

st.set_page_config(page_title="Hybrid Log Classifier", page_icon="🔎")
st.title("Hybrid Log Classifier")
st.caption("10 alarm categories · Regex → TF-IDF + Logistic Regression → optional Groq LLM")

@st.cache_resource
def get_classifier() -> LogClassifier:
    return LogClassifier()

with st.expander("Routing rules"):
    st.markdown(
        "- **Regex:** a known high-precision signature matches; classification ends immediately.\n"
        "- **ML:** no regex matches, the text contains vocabulary learned during training, and the "
        "TF-IDF + Logistic Regression confidence meets the threshold.\n"
        "- **LLM:** no useful ML vocabulary or confidence is below the threshold; Groq is called "
        "only when a key is configured. Otherwise the app abstains as unknown."
    )
    st.write("Categories:", ", ".join(CATEGORIES))

log_text = st.text_area("Paste an application log", placeholder="Failed login for user=demo")
if st.button("Classify log", type="primary"):
    if not log_text.strip():
        st.warning("Enter a log line first.")
    else:
        try:
            result = get_classifier().classify(log_text)
            save_result(log_text, result.category, result.tier, result.confidence, result.latency_ms)
            st.subheader(result.category.upper())
            col1, col2, col3 = st.columns(3)
            col1.metric("Selected stage", result.tier)
            col2.metric("Confidence", f"{result.confidence:.1%}")
            col3.metric("Latency", f"{result.latency_ms:.2f} ms")
            st.info(result.reason)
            if result.tier == "llm_not_configured":
                st.warning("Groq was not called. Add GROQ_API_KEY to .env and restart Streamlit to enable escalation.")
            elif result.tier == "llm_error":
                st.warning("Groq was attempted but failed; this result is an explicit abstention.")
        except Exception as exc:
            st.error("Classification failed.")
            st.caption(f"{type(exc).__name__}: {exc}")
