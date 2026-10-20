import logging
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .classifier import LogClassifier
from .persistence import save_result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="Hybrid Log Classifier", version="1.0.0")


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class ClassifyResponse(BaseModel):
    category: str
    categories: list[str]
    tier: str
    confidence: float
    reason: str
    latency_ms: float


@lru_cache(maxsize=1)
def get_classifier() -> LogClassifier:
    return LogClassifier()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyResponse)
def classify(request: ClassifyRequest) -> ClassifyResponse:
    try:
        result = get_classifier().classify(request.text)
        save_result(request.text, result.category, result.tier, result.confidence, result.latency_ms)
        return ClassifyResponse(
            category=result.category,
            categories=list(result.categories),
            tier=result.tier,
            confidence=result.confidence,
            reason=result.reason,
            latency_ms=result.latency_ms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Classification failed")
        raise HTTPException(status_code=500, detail="Classification failed. Check the terminal for details.") from exc
