"""The REST API and the static frontend it serves.

Why FastAPI rather than Streamlit: this is a tool someone runs on their own
machine and hands a report to a colleague. That is a request/response product,
not a notebook. Streamlit's own docs describe it for data exploration -- its
whole model is "script reruns on every interaction", which does not fit a batch
job that takes a log file and produces a triage report.

Why the frontend is hand-written HTML/CSS/JS with no framework: the UI has
eight elements and no state to speak of. A framework would add a build step, a
node_modules directory, and a second language to learn, in exchange for nothing.
The static file is served straight from disk by FastAPI, so `git clone` and
`uvicorn` is the whole setup.

The API shape is deliberately the same envelope across all five of my projects:
result, confidence, explain, sources, cost, latency. Consistency there is worth
more than local optimisation.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ML_CONFIDENCE_THRESHOLD, SEVERITY, SEVERITY_ORDER
from .llm_classifier import DEFAULT_MODEL, LLMUnavailable, classify_with_llm
from .pipeline import classify_batch, classify_one
from .store import category_breakdown, get_run, list_runs, save_run

app = FastAPI(
    title="Incident Triage Console",
    description="Classify application logs into incidents, cheapest tier first.",
    version="2.0.0",
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ClassifyRequest(BaseModel):
    """A single-line classification request.

    `allow_llm` is exposed so the UI can offer an explicitly offline mode. That
    matters: someone pasting a log line containing a customer name should be
    able to keep it on their machine, and that is only true if the LLM tier can
    be switched off from the request rather than only by deleting the env var.
    """

    text: str = Field(..., min_length=1, max_length=2000)
    allow_llm: bool = True


class BatchRequest(BaseModel):
    """A batch classification request.

    Accepts either raw lines or (text, timestamp) pairs. Timestamps are used
    for incident grouping; a line without one still classifies and still groups
    into an undated bucket.
    """

    lines: list[str] = Field(..., min_length=1, max_length=5000)
    timestamps: list[str | None] | None = None
    allow_llm: bool = True
    source: str | None = None


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

# Splits "[2026-09-30 02:14:01] some message" into a timestamp and the message.
# This is the single most common log format, so it is handled properly rather
# than assuming no timestamps exist.
_BRACKET_TS = re.compile(
    r"^\[?(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?)\]?\s*(?P<msg>.*)$"
)
_SYSLOG_TS = re.compile(
    r"^(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(?P<msg>.*)$"
)


def parse_log_line(raw: str) -> tuple[str, str | None]:
    """Split one raw log line into ``(message, timestamp_or_None)``.

    Why this is in the API rather than the pipeline: the pipeline's contract is
    a clean (text, timestamp) pair, and parsing is the caller's job. Keeping the
    boundary sharp means the classifier is never responsible for guessing which
    half of a string is the message -- which is exactly the kind of ambiguity
    that silently produces wrong incidents.

    Two formats are handled: bracketed ISO timestamps, which most application
    loggers emit, and syslog, which is older but still common. Anything else
    passes through untouched as an undated message.
    """
    line = raw.strip()
    if not line:
        return "", None

    for pattern in (_BRACKET_TS, _SYSLOG_TS):
        match = pattern.match(line)
        if match:
            message = match.group("msg").strip()
            if message:  # a timestamp with no message is not useful
                return message, match.group("ts")
    return line, None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Report whether the optional LLM tier is usable.

    Why expose this: the most likely first question about any LLM project is
    "what happens without a key", and the honest answer should be observable
    from the UI rather than asserted in a README.
    """
    has_key = bool(os.getenv("GROQ_API_KEY"))
    return {
        "status": "ok",
        "llm_available": has_key,
        "model": os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        "ml_threshold": ML_CONFIDENCE_THRESHOLD,
        # Declared, not probed. Probing would cost money on every page load.
        "note": "llm_available reflects key presence, not a live provider check",
    }


@app.post("/classify")
def classify(request: ClassifyRequest) -> dict:
    """Classify one log line.

    Returns the same envelope every project in this portfolio uses:
    result, confidence, explain, cost, latency.
    """
    row = classify_one(request.text, allow_llm=request.allow_llm)
    return {
        "category": row["category"],
        "severity": row["severity"],
        "confidence": row.get("confidence"),
        "explain": _explain(row),
        "tier_used": row["tier_used"],
        "matched": row.get("matched"),
        "raw_reply": row.get("raw_reply"),
        "cost_usd": row["estimated_cost_usd"],
        "latency_ms": row["latency_ms"],
        "note": row.get("note"),
    }


def _explain(row: dict) -> str:
    """Build a one-line human explanation of why a line landed where it did.

    Why this exists: a category on its own is not defensible. When an operator
    asks "why is this a Security Alert", the answer needs to be a specific rule
    or a specific confidence, not a shrug. Making the explanation a required
    part of the response means the UI cannot accidentally render a bare label.
    """
    tier = row["tier_used"]
    if tier == "regex":
        return f"Matched a written rule: /{row['matched']}/"
    if tier == "ml":
        return (
            f"No regex rule matched; TF-IDF + logistic regression predicted this "
            f"with {row['confidence']:.0%} confidence (threshold "
            f"{ML_CONFIDENCE_THRESHOLD:.0%})."
        )
    if tier == "llm":
        if row.get("raw_reply"):
            return f"Regex and ML both abstained; the model replied {row['raw_reply']!r}."
        return row.get("note") or "Regex and ML both abstained; the LLM tier was unavailable."
    return row.get("note") or "Neither the rules nor the model were confident enough."


@app.post("/classify/batch")
def classify_batch_endpoint(request: BatchRequest) -> dict:
    """Classify a batch of raw log lines and return the full triage report.

    This is the endpoint the product is actually about. A single-line call tells
    you one category; a batch tells you the tier mix, the cost avoided, the
    latency distribution, and the incidents -- which is the thing an operator
    would act on.

    The run is persisted so the history panel has something to show. Persistence
    failures are logged and swallowed rather than propagated: losing the history
    is a degraded experience, losing the report the user just asked for is not.
    """
    pairs: list[tuple[str, str | None]] = []
    for index, raw in enumerate(request.lines):
        message, timestamp = parse_log_line(raw)
        if not message:
            continue
        # An explicit timestamps[] array overrides parsed ones.
        if request.timestamps and index < len(request.timestamps):
            timestamp = request.timestamps[index] or timestamp
        pairs.append((message, timestamp))

    if not pairs:
        raise HTTPException(status_code=400, detail="No usable log lines in the request.")

    summary = classify_batch(pairs, allow_llm=request.allow_llm)
    summary["source"] = request.source

    try:
        run_id = save_run(summary)
        summary["run_id"] = run_id
    except Exception as exc:  # noqa: BLE001 - history is best-effort
        summary["run_id"] = None
        summary["history_error"] = f"{type(exc).__name__}: {exc}"

    return summary


@app.get("/runs")
def runs(limit: int = 20) -> dict:
    """Recent batch runs, newest first."""
    return {"runs": list_runs(limit=min(limit, 100))}


@app.get("/runs/{run_id}")
def run_detail(run_id: int) -> dict:
    """One run with every classification it produced."""
    result = get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    return result


@app.get("/stats")
def stats() -> dict:
    """Totals across all stored runs."""
    return {"categories": category_breakdown(), "severity_order": SEVERITY_ORDER}


@app.get("/model/benchmark")
def model_benchmark() -> dict:
    """Report which model is configured and why that one.

    Deliberately does not run the benchmark: that would spend money on every
    page load. The results are in docs/03-tech-stack.md and in the module
    docstring, and this endpoint just confirms what is live.
    """
    return {
        "configured_model": os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        "default_model": DEFAULT_MODEL,
        "llm_available": bool(os.getenv("GROQ_API_KEY")),
        "benchmark_note": (
            "qwen/qwen3.8-27b scored 15/15 on the held-out tier-3 set; "
            "gpt-oss-20b scored 3/10. See docs/03-tech-stack.md."
        ),
    }


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    """Serve the single-page UI."""
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(LLMUnavailable)
def llm_unavailable_handler(request, exc: LLMUnavailable) -> JSONResponse:
    """Turn an LLM outage into a clear 503 rather than a 500 stack trace.

    A 503 says "this capability is temporarily unavailable, retry or turn it
    off". A 500 says "the programmer made a mistake". The distinction matters
    to whoever is reading the terminal during a demo.
    """
    return JSONResponse(
        status_code=503,
        content={"detail": f"LLM tier unavailable: {exc}", "tier": "llm"},
    )
