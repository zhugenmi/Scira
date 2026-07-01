"""
Scira Logging Configuration

Centralized logging built on loguru with:
- Console output (always colored text)
- Rolling daily file logs (text or JSON, switchable via LOG_FORMAT env)
- request_id / run_id correlation via contextvars (auto-injected by patcher)
- InterceptHandler bridging stdlib logging (uvicorn, paper_search_mcp) into loguru
- Runtime level switching via set_log_level()

Initialization is idempotent and triggered at first import, so any entry point
(server / CLI / workflow) gets a configured logger without an explicit call.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from src.utils.context import get_current_request_id, get_current_run_id

PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_ACCESS_LOG = LOG_DIR / "access_{time:YYYYMMDD}.log"
_APP_LOG = LOG_DIR / "scira_{time:YYYYMMDD}.log"

_logger_initialized = False
_current_level = "INFO"


def _resolve_format() -> str:
    return os.getenv("LOG_FORMAT", "text").lower()


def _resolve_level(verbose: bool) -> str:
    if verbose:
        return "DEBUG"
    return os.getenv("LOG_LEVEL", "INFO").upper()


_TEXT_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "[{extra[request_id]}:{extra[run_id]}] "
    "{name}:{function}:{line} - {message}"
)

_TEXT_FORMAT_PLAIN = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "[{extra[request_id]}:{extra[run_id]}] "
    "{name}:{function}:{line} - {message}"
)

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>[{extra[request_id]}:{extra[run_id]}]</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


class InterceptHandler(logging.Handler):
    """Bridge stdlib logging records into loguru, preserving caller info."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except (ValueError, TypeError):
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _install_intercept() -> None:
    """Route stdlib logging (uvicorn, paper_search_mcp, etc.) through loguru."""
    root = logging.getLogger()
    root.handlers = [InterceptHandler()]
    root.setLevel(logging.DEBUG)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", "paper_search_mcp"):
        lg = logging.getLogger(name)
        lg.handlers = [InterceptHandler()]
        lg.propagate = False


def bridge_stdlib_logging() -> None:
    """Re-install the stdlib→loguru intercept.

    Call this after a third party (e.g. uvicorn) reconfigures stdlib logging
    via logging.config.dictConfig, which would otherwise overwrite the
    InterceptHandler installed at init time.
    """
    _install_intercept()


def _context_patcher(record: dict) -> None:
    record["extra"].setdefault("request_id", get_current_request_id())
    record["extra"].setdefault("run_id", get_current_run_id())


def init_logger(
    name: str = "scira",
    level: str = "INFO",
    verbose: bool = False,
) -> "logger":
    """Initialize console + file handlers. Idempotent via setup_logging."""
    global _current_level
    logger.remove()

    log_level = level.upper() if not verbose else "DEBUG"
    _current_level = log_level
    fmt = _resolve_format()

    logger.configure(patcher=_context_patcher)

    logger.add(
        sys.stdout,
        format=_CONSOLE_FORMAT,
        level=log_level,
        colorize=True,
    )

    if fmt == "json":
        logger.add(
            str(_APP_LOG),
            level="DEBUG",
            rotation="00:00",
            retention="7 days",
            compression="zip",
            encoding="utf-8",
            serialize=True,
            backtrace=True,
            diagnose=False,
        )
    else:
        logger.add(
            str(_APP_LOG),
            format=_TEXT_FORMAT_PLAIN,
            level="DEBUG",
            rotation="00:00",
            retention="7 days",
            compression="zip",
            encoding="utf-8",
            backtrace=True,
            diagnose=False,
        )

    logger.add(
        str(_ACCESS_LOG),
        format=_TEXT_FORMAT_PLAIN,
        level="INFO",
        rotation="00:00",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        filter=lambda record: record["name"].startswith("uvicorn.access"),
    )

    _install_intercept()

    logger.info(
        f"Logger initialized | Level: {log_level} | Format: {fmt} | "
        f"App log: {_APP_LOG} | Access log: {_ACCESS_LOG}"
    )
    return logger


def setup_logging(level: str = "INFO", verbose: bool = False) -> None:
    """Idempotent setup. Safe to call from any entry point."""
    global _logger_initialized
    if _logger_initialized:
        return
    init_logger(level=level, verbose=verbose)
    _logger_initialized = True


def set_log_level(level: str) -> str:
    """Switch log level at runtime. Re-adds handlers with the new level.

    Console handler level changes; file handler stays DEBUG (full capture).
    """
    global _logger_initialized, _current_level
    level = level.upper()
    if level not in ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"):
        raise ValueError(f"Invalid log level: {level}")
    _current_level = level
    logger.remove()
    logger.configure(patcher=_context_patcher)
    fmt = _resolve_format()
    logger.add(sys.stdout, format=_CONSOLE_FORMAT, level=level, colorize=True)
    if fmt == "json":
        logger.add(
            str(_APP_LOG),
            level="DEBUG",
            rotation="00:00",
            retention="7 days",
            compression="zip",
            encoding="utf-8",
            serialize=True,
            backtrace=True,
            diagnose=False,
        )
    else:
        logger.add(
            str(_APP_LOG),
            format=_TEXT_FORMAT_PLAIN,
            level="DEBUG",
            rotation="00:00",
            retention="7 days",
            compression="zip",
            encoding="utf-8",
            backtrace=True,
            diagnose=False,
        )
    logger.add(
        str(_ACCESS_LOG),
        format=_TEXT_FORMAT_PLAIN,
        level="INFO",
        rotation="00:00",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        filter=lambda record: record["name"].startswith("uvicorn.access"),
    )
    _install_intercept()
    logger.info(f"Log level switched to {level}")
    return level


def get_log_level() -> str:
    return _current_level


def get_logger(name: Optional[str] = None):
    """Bind a name to the logger for contextual identification."""
    if name:
        return logger.bind(name=name)
    return logger


def info(message: str, **kwargs: Any) -> None:
    logger.info(message, **kwargs)


def debug(message: str, **kwargs: Any) -> None:
    logger.debug(message, **kwargs)


def warning(message: str, **kwargs: Any) -> None:
    logger.warning(message, **kwargs)


def error(message: str, **kwargs: Any) -> None:
    logger.error(message, **kwargs)


def exception(message: str, **kwargs: Any) -> None:
    logger.exception(message, **kwargs)


class TokenTracker:
    """Track token usage and estimated costs."""

    PRICING = {
        "gpt-4o": {"input": 5.0, "output": 15.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "MiniMax-M2.5": {"input": 0.1, "output": 0.3},
        "claude-3-opus": {"input": 15.0, "output": 75.0},
        "claude-3-sonnet": {"input": 3.0, "output": 15.0},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},
        "doubao-seed-2-0-lite-260215": {"input": 0.07, "output": 0.21},
    }

    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.request_count = 0

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.request_count += 1

    def _pricing(self) -> dict:
        return self.PRICING.get(self.model_name, {"input": 5.0, "output": 15.0})

    def get_input_cost(self) -> float:
        return (self.total_input_tokens / 1_000_000) * self._pricing()["input"]

    def get_output_cost(self) -> float:
        return (self.total_output_tokens / 1_000_000) * self._pricing()["output"]

    def get_total_cost(self) -> float:
        return self.get_input_cost() + self.get_output_cost()

    def get_summary(self) -> dict:
        return {
            "model": self.model_name,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "request_count": self.request_count,
            "estimated_cost_usd": round(self.get_total_cost(), 4),
        }

    def __str__(self) -> str:
        s = self.get_summary()
        return (
            f"TokenTracker({self.model_name}): "
            f"{s['total_tokens']} tokens, ${s['estimated_cost_usd']:.4f} "
            f"({s['request_count']} requests)"
        )


_token_tracker: Optional[TokenTracker] = None


def get_token_tracker(model_name: str = "gpt-4o") -> TokenTracker:
    global _token_tracker
    if _token_tracker is None:
        _token_tracker = TokenTracker(model_name)
    return _token_tracker


def reset_token_tracker() -> None:
    global _token_tracker
    _token_tracker = None


def record_token_usage(response: Any, model_name: str = "gpt-4o") -> None:
    """Extract usage_metadata from a LangChain LLM response and feed the
    global TokenTracker, plus the llm_tokens_total / llm_requests_total metrics."""
    try:
        um = getattr(response, "usage_metadata", None)
        if not um:
            return
        in_tok = int(um.get("input_tokens", 0) or 0)
        out_tok = int(um.get("output_tokens", 0) or 0)
        if in_tok or out_tok:
            get_token_tracker(model_name).add_usage(in_tok, out_tok)
            from src.utils.metrics import get_registry
            r = get_registry()
            r.counter("llm_tokens_total").inc(float(in_tok), {"type": "input"})
            r.counter("llm_tokens_total").inc(float(out_tok), {"type": "output"})
            r.counter("llm_requests_total").inc()
    except Exception as e:
        logger.debug(f"token usage tracking skipped: {e}")


setup_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    verbose=os.getenv("LOG_VERBOSE") == "1",
)
