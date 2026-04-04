"""Postgres audit writer for secret access events.

Registered as a hook on get_secret() during Brain startup.
Buffers events in memory and flushes to Postgres asynchronously.
If Postgres is unavailable, events are logged to stdout only (via jarvis_common logger).
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

_buffer: deque[tuple[str, str, str, str]] = deque(maxlen=1000)
_flush_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_node: str = "brain"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS secret_access_log (
    id              BIGSERIAL PRIMARY KEY,
    key_name        TEXT NOT NULL,
    source          TEXT NOT NULL,
    accessed_at     TIMESTAMPTZ NOT NULL,
    node            TEXT NOT NULL,
    flushed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CREATE_INDEX_KEY_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_sal_key ON secret_access_log(key_name)"
)
CREATE_INDEX_ACCESSED_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_sal_accessed ON secret_access_log(accessed_at DESC)"
)

INSERT_SQL = """
INSERT INTO secret_access_log (key_name, source, accessed_at, node)
VALUES ($1, $2, $3::timestamptz, $4)
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
            await conn.executemany(INSERT_SQL, batch)
        logger.debug("secret_audit: flushed %d events to postgres", len(batch))
    except Exception as e:
        logger.warning(
            "secret_audit: flush failed (%s) — %d events lost", e, len(batch)
        )


async def ensure_table() -> None:
    """Create the secret_access_log table if it doesn't exist."""
    try:
        from brain.db.pool import get_pool

        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
            await conn.execute(CREATE_INDEX_KEY_SQL)
            await conn.execute(CREATE_INDEX_ACCESSED_SQL)
        logger.info("secret_audit: table ready")
    except Exception as e:
        logger.warning("secret_audit: table creation failed — %s", e)
