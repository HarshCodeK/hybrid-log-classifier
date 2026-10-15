from datetime import datetime
from pathlib import Path
from threading import Lock
import os

from fastapi import FastAPI, HTTPException, Request

from .observability import RequestMetrics
from pydantic import BaseModel, Field

from .domain import Classification, LogEvent
from .llm import GroqLLM
from .ml import MLClassifier
from .persistence import ClassificationStore
from .service import ClassifierService


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
    app = FastAPI(title="Hybrid Log Classifier", version="0.1.0")
    classifier = service
    classifier_lock = Lock()
    metrics = RequestMetrics()

    @app.middleware("http")
    async def observe_requests(request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)
        started = __import__("time").perf_counter()
        metrics.begin()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Process-Time-Ms"] = f"{(__import__('time').perf_counter() - started) * 1000:.2f}"
            return response
        finally:
            route = request.scope.get('route')
            route_name = getattr(route, 'path', '<unmatched>')
            metrics.finish(route_name, status_code, (__import__("time").perf_counter() - started) * 1000)

    @app.get("/metrics")
    def get_metrics() -> dict:
        return metrics.snapshot()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "llm": "configured" if os.getenv("GROQ_API_KEY") else "disabled"}

    @app.post("/classify", response_model=ClassifyResponse)
    def classify(request: ClassifyRequest) -> ClassifyResponse:
        nonlocal classifier
        if classifier is None:
            # Prevent duplicate model loads and SQLite handles during concurrent first requests.
            with classifier_lock:
                if classifier is None:
                    try:
                        classifier = build_service()
                    except RuntimeError as exc:
                        raise HTTPException(status_code=503, detail=str(exc)) from exc
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
