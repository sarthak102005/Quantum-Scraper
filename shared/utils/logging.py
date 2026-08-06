"""
shared/utils/logging.py

Configures structlog to emit JSON-formatted log entries.
Every MCP action must produce a JSON log entry through this module.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
) -> None:
    """Configure structlog for JSON output.

    Call once at application startup (main.py).

    Args:
        level: Python log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Optional file path for log output in addition to stdout.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=handlers,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named structlog logger.

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        A bound structlog logger instance.
    """
    return structlog.get_logger(name)
