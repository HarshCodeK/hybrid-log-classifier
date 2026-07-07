import time
import pandas as pd
import os

from src.regex_classifier import classify_regex
from src.ml_classifier import classify_ml
from src.llm_classifier import classify_llm
from src.monitor import init_db, log_result


def classify_log(text: str) -> dict:
    init_db()
    start = time.time()

    category = classify_regex(text)
    if category:
        latency = (time.time() - start) * 1000
        log_result(text, category, "regex", 1.0, latency)
        return {"text": text, "category": category, "tier_used": "regex", "confidence": 1.0, "latency_ms": round(latency, 2)}

    category, confidence = classify_ml(text)
    if category:
        latency = (time.time() - start) * 1000
        log_result(text, category, "ml", confidence, latency)
        return {"text": text, "category": category, "tier_used": "ml", "confidence": round(confidence, 4), "latency_ms": round(latency, 2)}

    category = classify_llm(text)
    latency = (time.time() - start) * 1000
    log_result(text, category, "llm", None, latency)
    return {"text": text, "category": category, "tier_used": "llm", "confidence": None, "latency_ms": round(latency, 2)}


if __name__ == "__main__":
    unseen_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "unseen_logs.csv")
    df = pd.read_csv(unseen_path)
    for text in df["log_text"]:
        result = classify_log(text)
        print(f"{result['tier_used']:6s} | {result['category']:22s} | {text}")
