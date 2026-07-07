import streamlit as st
import pandas as pd
import io

from src.pipeline import classify_log
from src.monitor import init_db, get_tier_counts

st.set_page_config(page_title="Hybrid Log Classifier", layout="wide")
init_db()

st.title("Hybrid Log Classifier")
st.markdown("Classifies log lines using **Regex → ML → LLM** (fastest first)")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Single Log Line")
    text = st.text_input("Enter a log line:", key="single_input")
    if st.button("Classify") and text:
        with st.spinner("Classifying..."):
            result = classify_log(text)
        c = result["category"]
        t = result["tier_used"]
        conf = result.get("confidence", "")
        lat = result.get("latency_ms", "")
        tier_colors = {"regex": "green", "ml": "orange", "llm": "red"}
        st.markdown(f"**Category:** {c}")
        st.markdown(f"**Tier:** :{tier_colors.get(t, 'blue')}[{t}]")
        if conf:
            st.markdown(f"**Confidence:** {conf}")
        st.markdown(f"**Latency:** {lat} ms")

with col2:
    st.subheader("Batch CSV Upload")
    uploaded = st.file_uploader("Upload CSV (must have 'log_text' column)", type="csv")
    if uploaded:
        df = pd.read_csv(uploaded)
        if "log_text" not in df.columns:
            st.error("CSV must contain a 'log_text' column")
        else:
            results = []
            progress = st.progress(0)
            for i, row in df.iterrows():
                results.append(classify_log(row["log_text"]))
                progress.progress((i + 1) / len(df))
            result_df = pd.DataFrame(results)
            st.dataframe(result_df, use_container_width=True)
            csv_buf = io.BytesIO()
            result_df.to_csv(csv_buf, index=False)
            st.download_button("Download Results", data=csv_buf.getvalue(), file_name="classified_logs.csv", mime="text/csv")

st.divider()
st.subheader("Tier Usage Summary")
counts = get_tier_counts()
if counts:
    chart_df = pd.DataFrame(list(counts.items()), columns=["Tier", "Count"])
    st.bar_chart(chart_df.set_index("Tier"))
else:
    st.info("No classifications logged yet. Classify some logs to see stats.")
