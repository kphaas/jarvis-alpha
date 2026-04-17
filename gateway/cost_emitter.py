"""Cost event buffer and flush — Gateway → Brain.

SQLite WAL buffer for crash safety. Background task flushes batches
to Brain's /v1/internal/cost-event endpoint.

Design decisions:
- SQLite WAL mode: survives Gateway crashes, events persist across restarts
- curl + asyncio.to_thread: Tailscale TLS compatibility (httpx fails with OpenSSL 3.x)
- 50-event batches, 5s sleep: prevent Brain DoS on reconnect (Decision #12)
- Fire-and-forget from caller perspective: buffer_event() never blocks adapter flow
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_gateway")

_DB_PATH = Path.home() / "jarvis-alpha" / "data" / "cost_buffer.db"
_BATCH_SIZE = 50
_FLUSH_INTERVAL_SEC = 5


def _init_db() -> sqlite3.Connection:
    """Open SQLite with WAL mode, create table if needed."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cost_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            flushed INTEGER DEFAULT 0
        )
    """
    )
    return conn


_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _init_db()
    return _conn


def buffer_event(
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    session_type: str | None = None,
    intent: str | None = None,
    executor: str = "gateway",
    on_behalf_of: str | None = None,
) -> None:
    """Buffer a cost event to SQLite. Non-blocking, never raises."""
    try:
        event = {
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "session_type": session_type,
            "intent": intent,
            "executor": executor,
            "on_behalf_of": on_behalf_of,
        }
        conn = _get_conn()
        conn.execute(
            "INSERT INTO cost_events (payload, created_at) VALUES (?, ?)",
            (json.dumps(event), datetime.now(timezone.utc).isoformat()),
        )
    except Exception as exc:
        logger.error("buffer_event failed: %s", exc)


def _flush_sync(brain_url: str, token: str, batch: list[tuple[int, str]]) -> list[int]:
    """Flush a batch of events to Brain. Returns list of successfully flushed IDs."""
    flushed_ids: list[int] = []
    for row_id, payload_json in batch:
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-sk",
                    "--max-time",
                    "10",
                    "-X",
                    "POST",
                    f"{brain_url}/v1/internal/cost-event",
                    "-H",
                    f"Authorization: Bearer {token}",
                    "-H",
                    "Content-Type: application/json",
                    "-d",
                    payload_json,
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            status = (result.stdout or "").strip()
            if status == "201":
                flushed_ids.append(row_id)
            else:
                logger.warning(
                    "cost_flush: brain returned %s for event %d", status, row_id
                )
        except Exception as exc:
            logger.error("cost_flush: event %d failed: %s", row_id, exc)
    return flushed_ids


async def flush_loop() -> None:
    """Background loop: flush buffered cost events to Brain in batches."""
    logger.info("cost_emitter flush_loop started")
    while True:
        try:
            brain_url = os.environ.get("JARVIS_ALPHA_BRAIN_URL", "").rstrip("/")
            token = os.environ.get("ALPHA_SERVICE_TOKEN", "")
            if not brain_url or not token:
                await asyncio.sleep(_FLUSH_INTERVAL_SEC)
                continue

            conn = _get_conn()
            rows = conn.execute(
                "SELECT id, payload FROM cost_events WHERE flushed = 0 ORDER BY id LIMIT ?",
                (_BATCH_SIZE,),
            ).fetchall()

            if not rows:
                await asyncio.sleep(_FLUSH_INTERVAL_SEC)
                continue

            flushed_ids = await asyncio.to_thread(_flush_sync, brain_url, token, rows)

            if flushed_ids:
                placeholders = ",".join("?" * len(flushed_ids))
                conn.execute(
                    f"DELETE FROM cost_events WHERE id IN ({placeholders})",
                    flushed_ids,
                )
                logger.info(
                    "cost_flush: %d/%d events flushed", len(flushed_ids), len(rows)
                )

        except Exception as exc:
            logger.error("flush_loop error: %s", exc)

        await asyncio.sleep(_FLUSH_INTERVAL_SEC)
