from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import asyncpg

from brain.config.logging_config import get_logger, new_trace_id
from brain.memory.memory import MemoryService

logger = get_logger("alpha_buddy")

BUDDY_INTERVAL = int(os.environ.get("BUDDY_INTERVAL_SECONDS", "60"))
ALERT_THRESHOLD_HOURS = 20


def _to_uuid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_DNS, user_id)


async def _write_event(
    conn: asyncpg.Connection,
    *,
    user_id: str | None,
    event_type: str,
    title: str,
    body: str = "",
    priority: int = 2,
) -> None:
    await conn.execute(
        """
        INSERT INTO alpha_buddy_events
          (user_id, event_type, title, body, priority)
        VALUES ($1, $2, $3, $4, $5)
        """,
        user_id,
        event_type,
        title,
        body,
        priority,
    )


async def _run_cycle(pool: asyncpg.Pool) -> None:
    new_trace_id()
    memory = MemoryService(pool)

    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT DISTINCT user_id FROM alpha_conversation_memory"
        )

    for row in users:
        user_id = row["user_id"]
        user_uuid = _to_uuid(user_id)

        try:
            eviction = await memory.evict_working()
            evicted = eviction.get("evicted", "0")

            async with pool.acquire() as conn:
                if evicted and evicted != "DELETE 0":
                    await _write_event(
                        conn,
                        user_id=user_id,
                        event_type="system",
                        title="Memory eviction complete",
                        body=f"Cleared expired working memory. Result: {evicted}",
                        priority=1,
                    )

            promotion = await memory.promote_to_semantic(user_uuid)
            promoted = promotion.get("promoted", 0)

            async with pool.acquire() as conn:
                if promoted > 0:
                    await _write_event(
                        conn,
                        user_id=user_id,
                        event_type="suggestion",
                        title=f"{promoted} memory promoted to semantic",
                        body="High-confidence memories are now part of permanent knowledge.",
                        priority=2,
                    )

                # Evict episodic memories older than 30 days
                episodic_evicted = await conn.execute(
                    """
                    DELETE FROM alpha_conversation_memory
                    WHERE user_id = $1
                      AND tier = 'episodic'
                      AND created_at < now() - interval '30 days'
                    """,
                    str(user_id),
                )

                # Cap episodic at 1000 rows — delete oldest beyond cap
                episodic_capped = await conn.execute(
                    """
                    DELETE FROM alpha_conversation_memory
                    WHERE id IN (
                        SELECT id FROM alpha_conversation_memory
                        WHERE user_id = $1 AND tier = 'episodic'
                        ORDER BY created_at ASC
                        OFFSET 1000
                    )
                    """,
                    str(user_id),
                )

                # Cap semantic at 200 rows — delete lowest importance beyond cap
                await conn.execute(
                    """
                    DELETE FROM alpha_conversation_memory
                    WHERE id IN (
                        SELECT id FROM alpha_conversation_memory
                        WHERE user_id = $1 AND tier = 'semantic'
                        ORDER BY importance_score ASC NULLS FIRST
                        OFFSET 200
                    )
                    """,
                    str(user_id),
                )

                if episodic_evicted != "DELETE 0" or episodic_capped != "DELETE 0":
                    await _write_event(
                        conn,
                        user_id=user_id,
                        event_type="system",
                        title="Memory optimization complete",
                        body=f"Episodic eviction: {episodic_evicted}. Cap enforcement: {episodic_capped}.",
                        priority=1,
                    )

            async with pool.acquire() as conn:
                await conn.execute(
                    "SELECT set_config('jarvis.current_user', $1, true)",
                    str(user_id),
                )
                aging = await conn.fetch(
                    """
                    SELECT id, summary
                    FROM alpha_conversation_memory
                    WHERE user_id = $1
                      AND tier = 'working'
                      AND created_at < now() - interval '20 hours'
                    LIMIT 5
                    """,
                    str(user_id),
                )

                if aging:
                    await _write_event(
                        conn,
                        user_id=user_id,
                        event_type="alert",
                        title=f"{len(aging)} working memories expiring soon",
                        body="These will be evicted within 4 hours unless marked persistent.",
                        priority=3,
                    )

        except Exception as e:
            logger.error("Buddy cycle error for user %s: %s", user_id, e)

    logger.info("Buddy cycle complete at %s", datetime.now(timezone.utc).isoformat())


async def run_buddy() -> None:
    logger.info("Buddy agent starting — interval %ss", BUDDY_INTERVAL)

    dsn = os.environ.get("ALPHA_DB_DSN")
    if not dsn:
        logger.error("ALPHA_DB_DSN not set — exiting")
        return

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    logger.info("Buddy DB pool ready")

    while True:
        try:
            await _run_cycle(pool)
        except Exception as e:
            logger.error("Buddy top-level error: %s", e)

        await asyncio.sleep(BUDDY_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_buddy())
