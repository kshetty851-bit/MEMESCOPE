"""Structured logging.

Every log line is JSON in deployed environments and human-readable locally.
A per-request `request_id` is bound via contextvars so it appears on every log
emitted while handling that request, including ones from library loggers.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import settings


def _drop_color_message_key(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """uvicorn duplicates the message under `color_message`; drop the noise."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging() -> None:
    """Route stdlib logging and structlog through one shared pipeline."""
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _drop_color_message_key,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.LOG_FORMAT == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL)

    # Hand library loggers to our handler rather than letting them format twice.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine", "alembic"):
        lib_logger = logging.getLogger(name)
        lib_logger.handlers = []
        lib_logger.propagate = True

    # uvicorn's access log duplicates our RequestContextMiddleware line.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
