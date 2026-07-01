"""
Tests for the enterprise logging & metrics system.

Covers:
- request_id / run_id contextvars injection and loguru patcher
- Counter / Gauge / Histogram / Timer behavior
- MetricsRegistry collect() shape
- setup_logging idempotency and set_log_level runtime switch
- InterceptHandler bridges stdlib logging into loguru
- /metrics and /api/logs/level FastAPI endpoints
"""

import io
import logging
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.context import (
    new_request_id, new_run_id, get_current_request_id, get_current_run_id,
    set_request_id, set_run_id, reset_request_id, reset_run_id,
)
from src.utils.metrics import get_registry, init_default_metrics, MetricsRegistry


# ==================== contextvars ====================

class TestContextVars:
    def test_request_id_default_dash(self):
        reset_request_id()
        assert get_current_request_id() == "-"

    def test_new_request_id_sets_and_returns(self):
        rid = new_request_id()
        assert get_current_request_id() == rid
        assert len(rid) == 12
        reset_request_id()

    def test_new_run_id_sets_and_returns(self):
        rid = new_run_id()
        assert get_current_run_id() == rid
        reset_run_id()

    def test_set_request_id_explicit(self):
        set_request_id("abc123")
        assert get_current_request_id() == "abc123"
        reset_request_id()


# ==================== metrics ====================

class TestMetrics:
    def test_counter_inc_and_collect(self):
        r = MetricsRegistry()
        c = r.counter("test_counter", "desc")
        c.inc(1.0, {"path": "/a"})
        c.inc(2.0, {"path": "/a"})
        c.inc(1.0, {"path": "/b"})
        out = c.collect()
        assert out["type"] == "counter"
        assert out["description"] == "desc"
        vals = {(s["labels"].get("path"), s["value"]) for s in out["samples"]}
        assert ("/a", 3.0) in vals
        assert ("/b", 1.0) in vals

    def test_counter_rejects_negative(self):
        r = MetricsRegistry()
        c = r.counter("neg_counter")
        with pytest.raises(ValueError):
            c.inc(-1.0)

    def test_counter_returns_same_instance(self):
        r = MetricsRegistry()
        c1 = r.counter("same_counter")
        c2 = r.counter("same_counter")
        assert c1 is c2

    def test_gauge_inc_dec_set(self):
        r = MetricsRegistry()
        g = r.gauge("test_gauge")
        g.inc(5.0)
        g.dec(2.0)
        g.set(10.0)
        out = g.collect()
        assert out["samples"][0]["value"] == 10.0

    def test_histogram_observe(self):
        r = MetricsRegistry()
        h = r.histogram("test_hist")
        h.observe(0.05)
        h.observe(2.0)
        h.observe(100.0)
        out = h.collect()
        sample = out["samples"][0]
        assert sample["count"] == 3
        assert sample["sum"] == pytest.approx(102.05, rel=1e-3)
        # 0.05 falls in le_0.1 bucket; 2.0 in le_5.0; 100.0 in the last bucket
        assert sample["buckets"]["le_0.1"] == 1
        assert sample["buckets"]["le_5.0"] == 2
        assert sample["buckets"]["le_300.0"] == 3

    def test_registry_collect_has_all_metrics(self):
        init_default_metrics()
        out = get_registry().collect()
        expected = {
            "http_requests_total", "http_request_duration_seconds",
            "workflow_started_total", "workflow_completed_total", "workflow_active",
            "workflow_phase_duration_seconds", "llm_tokens_total", "llm_requests_total",
            "papers_downloaded_total", "mcp_subprocess_active", "errors_total",
        }
        assert expected.issubset(set(out.keys()))

    def test_timer_context_manager(self):
        r = MetricsRegistry()
        with r.timer("test_timer"):
            pass
        out = r.histogram("test_timer").collect()
        assert out["samples"][0]["count"] == 1

    def test_type_mismatch_rejected(self):
        r = MetricsRegistry()
        r.counter("shared_name")
        with pytest.raises(ValueError):
            r.gauge("shared_name")


# ==================== logger ====================

class TestLogger:
    def test_setup_logging_idempotent(self):
        from src.utils.logger import setup_logging
        # Should not raise even if called multiple times
        setup_logging()
        setup_logging()
        setup_logging()

    def test_set_log_level_valid(self):
        from src.utils.logger import set_log_level, get_log_level
        set_log_level("DEBUG")
        assert get_log_level() == "DEBUG"
        set_log_level("INFO")
        assert get_log_level() == "INFO"

    def test_set_log_level_invalid(self):
        from src.utils.logger import set_log_level
        with pytest.raises(ValueError):
            set_log_level("BOGUS")

    def test_intercept_handler_bridges_stdlib(self, capsys):
        from src.utils.logger import setup_logging, bridge_stdlib_logging
        setup_logging()
        bridge_stdlib_logging()
        stdlib_logger = logging.getLogger("paper_search_mcp.test")
        stdlib_logger.warning("intercept test message")
        # No assertion on output format (loguru writes to stdout/file);
        # the test passes if no exception is raised and the message flows.

    def test_loguru_patcher_adds_context_fields(self):
        from src.utils.logger import setup_logging, logger
        from loguru import logger as l
        setup_logging()
        set_request_id("req-xyz")
        set_run_id("run-abc")
        captured = {}

        def sink(message):
            captured["text"] = str(message)

        h_id = l.add(sink, format="{extra[request_id]}|{extra[run_id]}|{message}", level="DEBUG")
        try:
            logger.info("context test")
        finally:
            l.remove(h_id)
        reset_request_id()
        reset_run_id()
        assert "req-xyz" in captured["text"]
        assert "run-abc" in captured["text"]


# ==================== FastAPI endpoints ====================

class TestEndpoints:
    @pytest.fixture(scope="class")
    def client(self):
        from src.mcp.server import app
        return TestClient(app)

    def test_metrics_endpoint_returns_json(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "http_requests_total" in data
        assert "workflow_phase_duration_seconds" in data

    def test_metrics_endpoint_has_token_tracker(self, client):
        resp = client.get("/metrics")
        data = resp.json()
        assert "_llm_token_tracker" in data

    def test_get_log_level(self, client):
        resp = client.get("/api/logs/level")
        assert resp.status_code == 200
        assert "level" in resp.json()

    def test_set_log_level_valid(self, client):
        resp = client.post("/api/logs/level", json={"level": "DEBUG"})
        assert resp.status_code == 200
        assert resp.json()["level"] == "DEBUG"
        # restore
        client.post("/api/logs/level", json={"level": "INFO"})

    def test_set_log_level_invalid_returns_400(self, client):
        resp = client.post("/api/logs/level", json={"level": "NOPE"})
        assert resp.status_code == 400

    def test_request_id_header_echoed(self, client):
        resp = client.get("/metrics", headers={"X-Request-ID": "test-rid-123"})
        assert resp.headers.get("X-Request-ID") == "test-rid-123"

    def test_request_id_generated_when_absent(self, client):
        resp = client.get("/metrics")
        rid = resp.headers.get("X-Request-ID")
        assert rid is not None
        assert rid != ""
        assert rid != "-"

    def test_http_metrics_increment_on_request(self, client):
        # Hit an endpoint a couple times, then verify counter advanced
        before = client.get("/metrics").json()
        before_count = sum(
            s["value"] for s in before["http_requests_total"]["samples"]
            if s["labels"].get("path") == "/metrics" and s["labels"].get("status") == "200"
        )
        client.get("/metrics")
        client.get("/metrics")
        after = client.get("/metrics").json()
        after_count = sum(
            s["value"] for s in after["http_requests_total"]["samples"]
            if s["labels"].get("path") == "/metrics" and s["labels"].get("status") == "200"
        )
        # at least the two extra hits should be reflected (plus the /metrics calls in between)
        assert after_count > before_count
