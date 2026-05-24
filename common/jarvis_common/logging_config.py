"""Shared structured logging for all JARVIS Alpha services."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default="no-trace"
)

_NODE = os.environ.get("JARVIS_NODE", "brain")
_RESERVED_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


def set_trace_id(trace_id: str) -> None:
    trace_id_var.set(trace_id)


def new_trace_id() -> str:
    tid = uuid.uuid4().hex
    set_trace_id(tid)
    return tid


class JarvisFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        import traceback as tb

        msg = record.getMessage()
        if record.exc_info and record.exc_info[0] is not None:
            msg += "\n" + "".join(tb.format_exception(*record.exc_info))

        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "node": _NODE,
            "trace_id": trace_id_var.get("no-trace"),
            "message": msg,
        }
        payload.update(_safe_extra(record))
        return json.dumps(payload, default=str)


def _safe_extra(record: logging.LogRecord) -> dict[str, object]:
    extras: dict[str, object] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED_RECORD_KEYS or key.startswith("_"):
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            extras[key] = value
        elif isinstance(value, (list, tuple, set)):
            extras[key] = list(value)
        elif isinstance(value, dict):
            extras[key] = value
    return extras


def get_logger(service: str) -> logging.Logger:
    logger = logging.getLogger(service)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = JarvisFormatter(service)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    logger.propagate = False
    return logger
