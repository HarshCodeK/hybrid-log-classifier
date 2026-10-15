from datetime import datetime
import logging
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from .domain import Classification, LogEvent
from .llm import GroqLLM
from .ml import MLClassifier
from .observability import ProcessMetrics
from .persistence import ClassificationStore
from .service import ClassifierService

logger = logging.getLogger(__name__)


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    timestamp: datetime | None = None


class ClassifyResponse(BaseModel):
    category: str
    tier: str
    confidence: float
    reason: str
    latency_ms: float


def build_service() -> ClassifierService:
    model_path = Path(os.getenv("MODEL_PATH", "models/classifier.joblib"))
    if not model_path.exists():
        raise RuntimeError(f"model artifact not found at {model_path}; run python scripts/train.py")
    threshold = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.30"))
    store = ClassificationStore(Path(os.getenv("DATABASE_PATH", "runtime/classifications.db")))
    api_key = os.getenv("GROQ_API_KEY", "")
    llm = GroqLLM(api_key=api_key) if api_key else None
    return ClassifierService(MLClassifier.load(model_path, threshold), store=store, llm=llm)


def create_app(service: ClassifierService | None = None) -> FastAPI:
    app = FastAPI(title="Hybrid Log Classifier", version="0.2.0")
    classifier = service
    metrics = ProcessMetrics()
    excluded_metrics_paths = {"/health", "/ready", "/metrics"}

    @app.middleware("http")
    async def collect_request_metrics(request, call_next):
        if request.url.path in excluded_metrics_paths:
            return await call_next(request)
        started = metrics.start()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            metrics.finish(f"{request.method} {request.url.path}", status_code, started)

    @app.get("/health")
    def health() -> dict[str, str]:
        # Liveness only. Deployment readiness is reported by /ready.
        return {"status": "ok", "llm": "configured" if os.getenv("GROQ_API_KEY") else "disabled"}

    @app.get("/ready")
    def ready(response: Response) -> dict[str, str]:
        nonlocal classifier
        try:
            if classifier is None:
                classifier = build_service()
            return {"status": "ready"}
        except Exception:
            logger.exception("readiness check failed")
            response.status_code = 503
            return {"status": "not_ready"}

    @app.get("/metrics")
    def get_metrics() -> dict:
        return metrics.snapshot()

    @app.post("/classify", response_model=ClassifyResponse)
    def classify(request: ClassifyRequest) -> ClassifyResponse:
        nonlocal classifier
        if classifier is None:
            try:
                classifier = build_service()
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail="classifier is not ready") from exc
        result: Classification = classifier.classify(LogEvent(request.text, request.timestamp))
        return ClassifyResponse(
            category=result.category.value,
            tier=result.tier.value,
            confidence=result.confidence,
            reason=result.reason,
            latency_ms=result.latency_ms,
        )

    return app


app = create_app()
