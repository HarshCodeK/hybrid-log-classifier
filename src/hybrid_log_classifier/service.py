from collections import deque
import os
from threading import Lock
from time import monotonic, perf_counter

import httpx

from .domain import Category, Classification, ClassificationTier, LogEvent
from .llm import LLMClassifier
from .ml import MLClassifier
from .persistence import ClassificationStore
from .rules import classify


_LLM_HITS: deque[float] = deque()
_LLM_HITS_LOCK = Lock()


def _llm_request_allowed() -> bool:
    try:
        limit = max(1, int(os.getenv("LLM_REQUESTS_PER_MINUTE", "30")))
    except ValueError:
        limit = 30
    now = monotonic()
    with _LLM_HITS_LOCK:
        while _LLM_HITS and now - _LLM_HITS[0] >= 60:
            _LLM_HITS.popleft()
        if len(_LLM_HITS) >= limit:
            return False
        _LLM_HITS.append(now)
        return True


class ClassifierService:
    def __init__(
        self,
        ml: MLClassifier,
        store: ClassificationStore | None = None,
        llm: LLMClassifier | None = None,
    ) -> None:
        self._ml = ml
        self._store = store
        self._llm = llm

    def classify(self, event: LogEvent) -> Classification:
        started = perf_counter()
        rule_match = classify(event.text)
        if rule_match:
            result = Classification(rule_match.category, ClassificationTier.RULE, 1.0, rule_match.reason, self._elapsed(started))
            self._save(event.text, result)
            return result

        category, confidence = self._ml.predict(event.text)
        if category is not None:
            result = Classification(category, ClassificationTier.ML, confidence, "local model cleared the confidence threshold", self._elapsed(started))
        elif self._llm is not None:
            if not _llm_request_allowed():
                result = Classification(Category.UNKNOWN, ClassificationTier.UNKNOWN, confidence, "LLM escalation limit reached; no provider request was made", self._elapsed(started))
            else:
                try:
                    output = self._llm.classify(event.text)
                    result = Classification(output.category, ClassificationTier.LLM, output.confidence, output.reason, self._elapsed(started))
                except (RuntimeError, ValueError, httpx.HTTPError):
                    result = Classification(Category.UNKNOWN, ClassificationTier.UNKNOWN, confidence, "LLM classification failed; request was not guessed", self._elapsed(started))
        else:
            result = Classification(Category.UNKNOWN, ClassificationTier.UNKNOWN, confidence, "local model abstained; no LLM provider was configured", self._elapsed(started))
        self._save(event.text, result)
        return result

    def _save(self, text: str, result: Classification) -> None:
        if self._store:
            self._store.save(text, result)

    @staticmethod
    def _elapsed(started: float) -> float:
        return (perf_counter() - started) * 1000
