"""Structured logging with run_id bound to every line.

V1 wrote 542 MB of unrotated free-text log per day across a 318 MB worker log,
and when something failed you could not reconstruct which run produced which
line. Here every record is JSON and carries the run context.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog

_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_source: ContextVar[str | None] = ContextVar("source", default=None)
_configured = False


def bind_run(run_id: str, source: str) -> None:
    _run_id.set(run_id)
    _source.set(source)


def clear_run() -> None:
    _run_id.set(None)
    _source.set(None)


def _inject_run(_logger, _method, event_dict):
    rid, src = _run_id.get(), _source.get()
    if rid:
        event_dict["run_id"] = rid
    if src:
        event_dict["source"] = src
    return event_dict


def configure(level: str = "INFO", json_output: bool = True) -> None:
    global _configured
    if _configured:
        return
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_run,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "prajna"):
    if not _configured:
        configure()
    return structlog.get_logger(name)
