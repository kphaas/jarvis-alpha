"""Generic Dead Letter Queue with SQLite WAL backing.

Pattern:
    dlq = DeadLetterQueue(db_path, queue_name='dream_goals', max_size=100)
    await dlq.enqueue(payload, reason='brain_unreachable')
    items = await dlq.drain(limit=50)
    await dlq.mark_flushed(ids)

Each queue_name is isolated — multiple queues can share one SQLite file.
Eviction is FIFO when max_size reached. Evicted items surface via on_evict callback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

log = logging.getLogger(__name__)

EvictCallback = Callable[[dict], Awaitable[None]]


@dataclass
class DLQItem:
    id: int
    queue_name: str
    payload: dict
    reason: str
    enqueued_at: str
    attempts: int


class DeadLetterQueue:
    """SQLite-backed DLQ with FIFO eviction.

    Thread/async safe via single-writer lock — sqlite3 is sync, so all calls
    run via asyncio.to_thread.
    """

    def __init__(
        self,
        db_path: Path,
        queue_name: str,
        max_size: int = 100,
        on_evict: Optional[EvictCallback] = None,
    ):
        self._db_path = Path(db_path)
        self._queue_name = queue_name
        self._max_size = max_size
        self._on_evict = on_evict
        self._lock = asyncio.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema_sync(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dlq_items (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_name   TEXT NOT NULL,
                    payload      TEXT NOT NULL,
                    reason       TEXT NOT NULL,
                    enqueued_at  TEXT NOT NULL,
                    attempts     INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dlq_queue ON dlq_items(queue_name, id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dlq_enqueued ON dlq_items(enqueued_at)"
            )
        finally:
            conn.close()

    def _init_schema(self) -> None:
        self._init_schema_sync()

    def _size_sync(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM dlq_items WHERE queue_name = ?",
                (self._queue_name,),
            ).fetchone()
            return int(row["n"])
        finally:
            conn.close()

    def _enqueue_sync(
        self, payload_json: str, reason: str
    ) -> tuple[int, Optional[dict]]:
        evicted_item: Optional[dict] = None
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT COUNT(*) AS n FROM dlq_items WHERE queue_name = ?",
                (self._queue_name,),
            ).fetchone()["n"]

            if current >= self._max_size:
                evict_row = conn.execute(
                    """
                    SELECT id, queue_name, payload, reason, enqueued_at, attempts
                    FROM dlq_items
                    WHERE queue_name = ?
                    ORDER BY id ASC LIMIT 1
                    """,
                    (self._queue_name,),
                ).fetchone()
                if evict_row:
                    evicted_item = {
                        "id": evict_row["id"],
                        "queue_name": evict_row["queue_name"],
                        "payload": json.loads(evict_row["payload"]),
                        "reason": evict_row["reason"],
                        "enqueued_at": evict_row["enqueued_at"],
                        "attempts": evict_row["attempts"],
                    }
                    conn.execute(
                        "DELETE FROM dlq_items WHERE id = ?", (evict_row["id"],)
                    )

            cursor = conn.execute(
                """
                INSERT INTO dlq_items (queue_name, payload, reason, enqueued_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    self._queue_name,
                    payload_json,
                    reason,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            new_id = int(cursor.lastrowid or 0)
            conn.execute("COMMIT")
            return new_id, evicted_item
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    async def enqueue(self, payload: dict, reason: str) -> int:
        """Enqueue payload. Returns new row id. Fires on_evict if capacity forces eviction."""
        payload_json = json.dumps(payload, default=str)
        async with self._lock:
            new_id, evicted = await asyncio.to_thread(
                self._enqueue_sync, payload_json, reason
            )
        if evicted and self._on_evict:
            try:
                await self._on_evict(evicted)
            except Exception as e:
                log.error("dlq on_evict callback failed: %s", e)
        log.info(
            "dlq[%s] enqueue id=%d reason=%s evicted=%s",
            self._queue_name,
            new_id,
            reason,
            evicted["id"] if evicted else None,
        )
        return new_id

    def _drain_sync(self, limit: int) -> list[DLQItem]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, queue_name, payload, reason, enqueued_at, attempts
                FROM dlq_items
                WHERE queue_name = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (self._queue_name, limit),
            ).fetchall()
            return [
                DLQItem(
                    id=r["id"],
                    queue_name=r["queue_name"],
                    payload=json.loads(r["payload"]),
                    reason=r["reason"],
                    enqueued_at=r["enqueued_at"],
                    attempts=r["attempts"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    async def drain(self, limit: int = 50) -> list[DLQItem]:
        """Return oldest items up to limit. Does not delete — caller must mark_flushed."""
        return await asyncio.to_thread(self._drain_sync, limit)

    def _mark_flushed_sync(self, ids: list[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                f"DELETE FROM dlq_items WHERE queue_name = ? AND id IN ({placeholders})",
                (self._queue_name, *ids),
            )
            deleted = cursor.rowcount
            conn.execute("COMMIT")
            return deleted
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    async def mark_flushed(self, ids: list[int]) -> int:
        """Delete items that were successfully flushed. Returns rows removed."""
        async with self._lock:
            return await asyncio.to_thread(self._mark_flushed_sync, ids)

    def _bump_attempts_sync(self, ids: list[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                f"""
                UPDATE dlq_items
                SET attempts = attempts + 1
                WHERE queue_name = ? AND id IN ({placeholders})
                """,
                (self._queue_name, *ids),
            )
            bumped = cursor.rowcount
            conn.execute("COMMIT")
            return bumped
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    async def bump_attempts(self, ids: list[int]) -> int:
        """Increment attempt counter for items that failed to flush."""
        async with self._lock:
            return await asyncio.to_thread(self._bump_attempts_sync, ids)

    async def size(self) -> int:
        return await asyncio.to_thread(self._size_sync)
