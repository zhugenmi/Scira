"""
Request/run correlation context.

Provides contextvars-based IDs that propagate through asyncio tasks and
threads (via loguru's patcher) so every log line can be tied to the HTTP
request and workflow run that produced it.

contextvars is chosen over threading.local because Scira runs on asyncio
(FastAPI + uvicorn); threading.local would lose the ID when control jumps
between executor threads and the event loop.
"""

from contextvars import ContextVar
from typing import Optional
import uuid

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
run_id_var: ContextVar[str] = ContextVar("run_id", default="-")


def _short_uuid() -> str:
    return uuid.uuid4().hex[:12]


def new_request_id() -> str:
    rid = _short_uuid()
    request_id_var.set(rid)
    return rid


def new_run_id() -> str:
    rid = _short_uuid()
    run_id_var.set(rid)
    return rid


def get_current_request_id() -> str:
    return request_id_var.get()


def get_current_run_id() -> str:
    return run_id_var.get()


def set_request_id(rid: str) -> None:
    request_id_var.set(rid)


def set_run_id(rid: str) -> None:
    run_id_var.set(rid)


def reset_request_id() -> None:
    request_id_var.set("-")


def reset_run_id() -> None:
    run_id_var.set("-")


def bind_context(request_id: Optional[str] = None, run_id: Optional[str] = None) -> None:
    """Set both IDs at once. None leaves the value unchanged."""
    if request_id is not None:
        request_id_var.set(request_id)
    if run_id is not None:
        run_id_var.set(run_id)
