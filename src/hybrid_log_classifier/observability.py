"""Small process-local HTTP metrics; deliberately not a distributed telemetry system."""
from collections import Counter
from threading import Lock


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active = 0
        self._total = 0
        self._errors = 0
        self._duration_ms = 0.0
        self._by_route: Counter[str] = Counter()
        self._by_status: Counter[str] = Counter()

    def begin(self) -> None:
        with self._lock:
            self._active += 1

    def finish(self, path: str, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            self._total += 1
            self._errors += int(status_code >= 500)
            self._duration_ms += max(0.0, duration_ms)
            self._by_route[path] += 1
            self._by_status[str(status_code)] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "scope": "this_process_only",
                "requests_total": self._total,
                "requests_active": self._active,
                "server_errors_total": self._errors,
                "mean_request_duration_ms": round(self._duration_ms / self._total, 3) if self._total else 0.0,
                "requests_by_route": dict(self._by_route),
                "responses_by_status": dict(self._by_status),
            }
