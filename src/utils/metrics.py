"""
Lightweight in-process metrics collection.

Zero-dependency Counter / Gauge / Histogram / Timer plus a process-global
Registry exposed via /metrics as JSON. Thread-safe via a single GIL-protected
lock per metric; sufficient for Scira's single-process workload.

Deliberately not Prometheus: avoids the prometheus-client dependency and the
exposition-format complexity. The JSON shape is structured so a thin Prometheus
adapter could be layered on later without touching call sites.
"""

import threading
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

DEFAULT_BUCKETS: Tuple[float, ...] = (0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0)


def _labels_key(labels: Optional[Dict[str, str]]) -> str:
    if not labels:
        return ""
    return "|".join(f"{k}={labels[k]}" for k in sorted(labels))


class Counter:
    """Monotonic counter. Only inc(); dec is not allowed."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._values: Dict[str, float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        if amount < 0:
            raise ValueError("Counter can only be incremented")
        key = _labels_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def collect(self) -> Dict[str, Any]:
        with self._lock:
            samples = []
            for key, val in self._values.items():
                label_dict = {}
                if key:
                    for pair in key.split("|"):
                        k, v = pair.split("=", 1)
                        label_dict[k] = v
                samples.append({"labels": label_dict, "value": val})
        return {"type": "counter", "description": self.description, "samples": samples}


class Gauge:
    """Gauge that can inc/dec/set."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._values: Dict[str, float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        key = _labels_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        self.inc(-amount, labels)

    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        key = _labels_key(labels)
        with self._lock:
            self._values[key] = value

    def collect(self) -> Dict[str, Any]:
        with self._lock:
            samples = []
            for key, val in self._values.items():
                label_dict = {}
                if key:
                    for pair in key.split("|"):
                        k, v = pair.split("=", 1)
                        label_dict[k] = v
                samples.append({"labels": label_dict, "value": val})
        return {"type": "gauge", "description": self.description, "samples": samples}


class Histogram:
    """Latency histogram with fixed buckets + count/sum."""

    def __init__(self, name: str, description: str = "", buckets: Tuple[float, ...] = DEFAULT_BUCKETS):
        self.name = name
        self.description = description
        self.buckets = sorted(buckets)
        self._counts: Dict[str, List[int]] = {}
        self._sums: Dict[str, float] = {}
        self._totals: Dict[str, int] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        key = _labels_key(labels)
        with self._lock:
            if key not in self._counts:
                self._counts[key] = [0] * len(self.buckets)
                self._sums[key] = 0.0
                self._totals[key] = 0
            for i, b in enumerate(self.buckets):
                if value <= b:
                    self._counts[key][i] += 1
            self._sums[key] += value
            self._totals[key] += 1

    def collect(self) -> Dict[str, Any]:
        with self._lock:
            samples = []
            for key in self._counts:
                label_dict = {}
                if key:
                    for pair in key.split("|"):
                        k, v = pair.split("=", 1)
                        label_dict[k] = v
                samples.append({
                    "labels": label_dict,
                    "buckets": {f"le_{b}": c for b, c in zip(self.buckets, self._counts[key])},
                    "count": self._totals[key],
                    "sum": round(self._sums[key], 4),
                })
        return {"type": "histogram", "description": self.description, "samples": samples}


class MetricsRegistry:
    """Process-global registry. Get via get_registry()."""

    def __init__(self) -> None:
        self._metrics: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, description: str = "") -> Counter:
        with self._lock:
            existing = self._metrics.get(name)
            if isinstance(existing, Counter):
                return existing
            if existing is not None:
                raise ValueError(f"Metric {name} already registered as different type")
            m = Counter(name, description)
            self._metrics[name] = m
            return m

    def gauge(self, name: str, description: str = "") -> Gauge:
        with self._lock:
            existing = self._metrics.get(name)
            if isinstance(existing, Gauge):
                return existing
            if existing is not None:
                raise ValueError(f"Metric {name} already registered as different type")
            m = Gauge(name, description)
            self._metrics[name] = m
            return m

    def histogram(self, name: str, description: str = "", buckets: Tuple[float, ...] = DEFAULT_BUCKETS) -> Histogram:
        with self._lock:
            existing = self._metrics.get(name)
            if isinstance(existing, Histogram):
                return existing
            if existing is not None:
                raise ValueError(f"Metric {name} already registered as different type")
            m = Histogram(name, description, buckets)
            self._metrics[name] = m
            return m

    @contextmanager
    def timer(self, name: str, labels: Optional[Dict[str, str]] = None) -> Iterator[None]:
        h = self.histogram(name)
        start = time.perf_counter()
        try:
            yield
        finally:
            h.observe(time.perf_counter() - start, labels)

    def time(self, name: str, labels: Optional[Dict[str, str]] = None) -> Callable:
        def deco(fn: Callable) -> Callable:
            @wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.timer(name, labels):
                    return fn(*args, **kwargs)
            return wrapper
        return deco

    def collect(self) -> Dict[str, Any]:
        with self._lock:
            return {name: m.collect() for name, m in self._metrics.items()}


_registry: Optional[MetricsRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> MetricsRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = MetricsRegistry()
    return _registry


def init_default_metrics() -> None:
    """Pre-register the standard Scira metrics so /metrics is non-empty
    even before any observation."""
    r = get_registry()
    r.counter("http_requests_total", "Total HTTP requests")
    r.histogram("http_request_duration_seconds", "HTTP request latency")
    r.counter("workflow_started_total", "Workflows started")
    r.counter("workflow_completed_total", "Workflows completed")
    r.gauge("workflow_active", "Currently active workflows")
    r.histogram("workflow_phase_duration_seconds", "Per-phase workflow duration")
    r.counter("llm_tokens_total", "LLM tokens consumed")
    r.counter("llm_requests_total", "LLM requests made")
    r.counter("papers_downloaded_total", "PDFs downloaded and parsed")
    r.gauge("mcp_subprocess_active", "Currently running MCP subprocesses")
    r.counter("errors_total", "Errors encountered")
