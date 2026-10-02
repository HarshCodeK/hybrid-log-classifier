"""FastAPI service. The primary interface.

Run:  uvicorn src.api:app --reload     then open http://localhost:8000/docs
"""
from datetime import datetime

from pydantic import BaseModel, Field

from fastapi import FastAPI

from . import models, store
from .llm_tier import available
from .pipeline import classify_batch, classify_one

app = FastAPI(title="Hybrid Log Classifier", version="1.0.0")


class Line(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    timestamp: datetime | None = None


class Batch(BaseModel):
    lines: list[Line] = Field(..., min_length=1, max_length=5000)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "llm_available": available(),
        "default_model": models.DEFAULT_MODEL,
        "tiers": ["regex", "ml", "llm"],
    }


@app.get("/models")
def list_models():
    """What the LLM tier can be pointed at, with prices."""
    return {"models": [
        {"id": mid, "label": label, "input_per_1m": pin, "output_per_1m": pout, "usable": ok}
        for mid, (label, pin, pout, ok) in models.MODELS.items()
    ]}


@app.post("/classify")
def classify(line: Line):
    return classify_one(line.text)


@app.post("/classify/batch")
def classify_batch_endpoint(batch: Batch, save: bool = True):
    """Classify a batch and return incidents ranked worst-first."""
    summary = classify_batch([(l.text, l.timestamp) for l in batch.lines])
    if save:
        try:
            store.save(summary)
        except Exception:
            # History is a convenience. Never fail a successful triage over it.
            pass
    return summary


@app.get("/runs")
def runs(limit: int = 10):
    return {"runs": store.recent(limit)}
