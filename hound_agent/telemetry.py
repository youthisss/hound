"""Process-local bounded operational metrics with no artifact payloads."""
from __future__ import annotations

import threading
from collections import defaultdict, deque


class TelemetryRegistry:
    def __init__(self, max_observations: int = 10000):
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._observations: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=max_observations))

    def increment(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self._counters[name] += value

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._observations[name].append(value)

    def snapshot(self) -> dict:
        with self._lock:
            observations = {name: _summary(list(values)) for name, values in self._observations.items()}
            return {
                "counters": dict(sorted(self._counters.items())),
                "gauges": dict(sorted(self._gauges.items())),
                "observations": dict(sorted(observations.items())),
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._observations.clear()


def _summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50": ordered[_percentile_index(len(ordered), 0.50)],
        "p95": ordered[_percentile_index(len(ordered), 0.95)],
        "max": ordered[-1],
    }


def _percentile_index(length: int, percentile: float) -> int:
    return min(length - 1, max(0, int((length - 1) * percentile + 0.5)))


telemetry = TelemetryRegistry()
