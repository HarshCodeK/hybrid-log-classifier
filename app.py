from pathlib import Path
import csv
import os
import sys

import streamlit as st

# Make the src-layout package importable on Streamlit Community Cloud as well as locally.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hybrid_log_classifier.api import build_service
from hybrid_log_classifier.domain import LogEvent
from hybrid_log_classifier.ml import train_model


st.set_page_config(page_title="Hybrid Log Classifier", page_icon="🔎")
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


text = st.text_area("Log line", placeholder="failed login user=alice ip=203.0.113.7")
if st.button("Classify"):
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
