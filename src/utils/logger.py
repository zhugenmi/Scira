"""
Scira Logging Configuration

Provides centralized logging with:
- Console output (colored)
- Rolling file logs in logs/ directory
- Session-based log files
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Loguru
from loguru import logger

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def init_logger(
    name: str = "scira",
    level: str = "INFO",
    verbose: bool = False,
) -> "logger":
    """
    Initialize the Scira logger with console and file handlers.

    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        verbose: Enable verbose (DEBUG) logging

    Returns:
        Configured logger instance
    """
    # Remove default handler
    logger.remove()

    # Determine log level
    log_level = level.upper() if not verbose else "DEBUG"

    # Console handler with colors
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True,
    )

    # Session-based log file
    session_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"scira_{session_time}.log"

    logger.add(
        str(log_file),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",  # File gets all levels
        rotation="10 MB",  # Rotate when file reaches 10MB
        retention="7 days",  # Keep logs for 7 days
        compression="zip",  # Compress rotated logs
        encoding="utf-8",
    )

    # Store log file path for reference
    logger.bind(log_file=str(log_file))

    logger.info(f"Logger initialized | Level: {log_level} | Log file: {log_file}")

    return logger


def get_logger(name: Optional[str] = None):
    """
    Get a logger instance.

    Args:
        name: Optional logger name (defaults to 'scira')

    Returns:
        Logger instance
    """
    if name:
        return logger.bind(name=name)
    return logger


# Initialize default logger
_logger_initialized = False


def setup_logging(level: str = "INFO", verbose: bool = False):
    """Setup logging with default configuration."""
    global _logger_initialized
    if not _logger_initialized:
        init_logger(level=level, verbose=verbose)
        _logger_initialized = True


# Convenience functions
def info(message: str, **kwargs):
    """Log info message."""
    logger.info(message, **kwargs)


def debug(message: str, **kwargs):
    """Log debug message."""
    logger.debug(message, **kwargs)


def warning(message: str, **kwargs):
    """Log warning message."""
    logger.warning(message, **kwargs)


def error(message: str, **kwargs):
    """Log error message."""
    logger.error(message, **kwargs)


def exception(message: str, **kwargs):
    """Log exception with traceback."""
    logger.exception(message, **kwargs)


# Token tracking utilities
class TokenTracker:
    """Track token usage and estimated costs."""

    # Pricing per 1M tokens (USD)
    PRICING = {
        "gpt-4o": {"input": 5.0, "output": 15.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "MiniMax-M2.5": {"input": 0.1, "output": 0.3},  # Estimate
        "claude-3-opus": {"input": 15.0, "output": 75.0},
        "claude-3-sonnet": {"input": 3.0, "output": 15.0},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},
        # Volcengine doubao-seed-2.0-lite — ESTIMATE, verify against official
        # pricing page. Lite models are cheap; these values prevent the unknown
        # model from falling back to gpt-4o pricing ($5/$15) which would
        # overstate cost by ~50x.
        "doubao-seed-2-0-lite-260215": {"input": 0.07, "output": 0.21},
    }

    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.request_count = 0

    def add_usage(self, input_tokens: int, output_tokens: int):
        """Add token usage from a request."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.request_count += 1

    def _pricing(self) -> dict:
        """Resolve pricing for the current model, falling back to gpt-4o."""
        return self.PRICING.get(self.model_name, {"input": 5.0, "output": 15.0})

    def get_input_cost(self) -> float:
        """Calculate input cost in USD."""
        pricing = self._pricing()
        return (self.total_input_tokens / 1_000_000) * pricing["input"]

    def get_output_cost(self) -> float:
        """Calculate output cost in USD."""
        pricing = self._pricing()
        return (self.total_output_tokens / 1_000_000) * pricing["output"]

    def get_total_cost(self) -> float:
        """Calculate total cost in USD."""
        return self.get_input_cost() + self.get_output_cost()

    def get_summary(self) -> dict:
        """Get usage summary."""
        return {
            "model": self.model_name,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "request_count": self.request_count,
            "estimated_cost_usd": round(self.get_total_cost(), 4),
        }

    def __str__(self) -> str:
        summary = self.get_summary()
        return (
            f"TokenTracker({self.model_name}): "
            f"{summary['total_tokens']} tokens, "
            f"${summary['estimated_cost_usd']:.4f} "
            f"({summary['request_count']} requests)"
        )


# Global token tracker instance
_token_tracker: Optional[TokenTracker] = None


def get_token_tracker(model_name: str = "gpt-4o") -> TokenTracker:
    """Get or create the global token tracker."""
    global _token_tracker
    if _token_tracker is None:
        _token_tracker = TokenTracker(model_name)
    return _token_tracker


def reset_token_tracker():
    """Reset the token tracker."""
    global _token_tracker
    _token_tracker = None


def record_token_usage(response: Any, model_name: str = "gpt-4o") -> None:
    """
    Extract usage_metadata from a LangChain LLM response and feed the global
    TokenTracker. Safe to call on any response object; no-ops if usage_metadata
    is absent. Used by BaseAgent and by standalone agents (e.g. RetrievalAgent)
    that call llm.invoke directly without going through BaseAgent.invoke.
    """
    try:
        um = getattr(response, "usage_metadata", None)
        if not um:
            return
        in_tok = int(um.get("input_tokens", 0) or 0)
        out_tok = int(um.get("output_tokens", 0) or 0)
        if in_tok or out_tok:
            get_token_tracker(model_name).add_usage(in_tok, out_tok)
    except Exception as e:
        logger.debug(f"token usage tracking skipped: {e}")
