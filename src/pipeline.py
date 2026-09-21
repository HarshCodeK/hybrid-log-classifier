import time
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

    # Tier 3: LLM. Degrade gracefully when it's unavailable (missing key,
    # missing package, provider error) instead of crashing the request.
    reason = None
    try:
        category = classify_llm(text)
    except Exception as e:  # noqa: BLE001 - any tier-3 failure falls back
        category, reason = "Unknown", f"llm_unavailable: {e.__class__.__name__}"

    latency = (time.time() - start) * 1000
    log_result(text, category, "llm", None, latency)
    result = {"text": text, "category": category, "tier_used": "llm", "confidence": None, "latency_ms": round(latency, 2)}
    if reason:
        result["note"] = reason
    return result


if __name__ == "__main__":
    import pandas as pd
    unseen_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "unseen_logs.csv")
    df = pd.read_csv(unseen_path)
    for text in df["log_text"]:
        result = classify_log(text)
        print(f"{result['tier_used']:6s} | {result['category']:22s} | {text}")
