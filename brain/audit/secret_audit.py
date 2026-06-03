"""Postgres audit writer for secret access events.

Registered as a hook on get_secret() during Brain startup.
Buffers events in memory and flushes to Postgres asynchronously.
If Postgres is unavailable, events are logged to stdout only (via jarvis_common logger).
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from datetime import datetime

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

_buffer: deque[tuple[str, str, str, str]] = deque(maxlen=1000)
_flush_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_node: str = "brain"

READINESS_SQL = """
SELECT
    to_regclass('public.secret_access_log') IS NOT NULL AS has_table,
    to_regprocedure(
        'public.record_secret_access(text,text,timestamp with time zone,text)'
    ) IS NOT NULL AS has_writer,
    has_function_privilege(
        current_user,
        'public.record_secret_access(text,text,timestamp with time zone,text)',
        'EXECUTE'
    ) AS can_execute
"""

INSERT_SQL = """
SELECT public.record_secret_access($1, $2, $3::timestamptz, $4)
"""


def init_audit(loop: asyncio.AbstractEventLoop, node: str = "brain") -> None:
    """Store the event loop reference for async flushing."""
    global _loop, _node
    _loop = loop
    _node = node


def audit_hook(key: str, source: str, ts: str) -> None:
    """Synchronous hook called from get_secret(). Buffers and schedules flush."""
    _buffer.append((key, source, ts, _node))
    if _loop and _loop.is_running():
        _loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_flush()))


async def _flush() -> None:
    """Flush buffered events to Postgres."""
    if not _buffer:
        return
    with _flush_lock:
        batch = []
        while _buffer:
            batch.append(_buffer.popleft())
        if not batch:
            return
    try:
        from brain.db.pool import get_pool

        pool = get_pool()
        async with pool.acquire() as conn:
            parsed = [(k, s, datetime.fromisoformat(ts), n) for k, s, ts, n in batch]
            await conn.executemany(INSERT_SQL, parsed)
        logger.debug("secret_audit: flushed %d events to postgres", len(batch))
    except Exception as e:
        logger.warning(
            "secret_audit: flush failed (%s) — %d events lost", e, len(batch)
        )


async def ensure_table() -> None:
    """Verify secret audit storage is ready.

    Runtime runs as jarvis_alpha_writer, so schema creation and grant repair must
    happen in migrations. This check is intentionally read-only.
    """
    try:
        from brain.db.pool import get_pool

        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(READINESS_SQL)
        if row and row["has_table"] and row["has_writer"] and row["can_execute"]:
            logger.info("secret_audit: writer ready")
            return
        logger.warning(
            "secret_audit: writer not ready (table=%s function=%s execute=%s)",
            bool(row and row["has_table"]),
            bool(row and row["has_writer"]),
            bool(row and row["can_execute"]),
        )
    except Exception as e:
        logger.warning("secret_audit: readiness check failed — %s", e)
