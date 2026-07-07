from fastapi import FastAPI
from pydantic import BaseModel

from src.pipeline import classify_log
from src.monitor import get_tier_counts

app = FastAPI(title="Hybrid Log Classifier")


class ClassifyRequest(BaseModel):
    text: str


@app.post("/classify")
def classify(request: ClassifyRequest):
    return classify_log(request.text)


@app.get("/stats")
def stats():
    return get_tier_counts()
