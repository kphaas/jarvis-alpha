from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import asyncpg

from jarvis_common.logging_config import get_logger, new_trace_id

logger = get_logger("alpha_buddy")

BUDDY_INTERVAL = int(os.environ.get("BUDDY_INTERVAL_SECONDS", "60"))
ALERT_THRESHOLD_HOURS = 20

_VALID_BUDDY_EVENT_TYPES = frozenset({"alert", "reminder", "suggestion", "system"})


def _normalize_buddy_event_type(event_type: str) -> str:
    et = (event_type or "").strip().lower()
    if et in _VALID_BUDDY_EVENT_TYPES:
        return et
    if et in ("eviction", "promotion", "maintenance"):
        return "system"
    return "system"


def _normalize_buddy_priority(priority: int | str | None) -> int:
    if priority is None:
        return 2
    if isinstance(priority, int):
        return priority
    p = str(priority).strip().lower()
    if p in ("info", "low"):
        return 1
    if p in ("normal", "medium", ""):
        return 2
    if p in ("high", "alert", "critical", "warn", "warning"):
        return 3
    return 2


async def _write_event(
    pool: asyncpg.Pool,
    *,
    user_id: str | None,
    event_type: str,
    title: str,
    body: str = "",
    priority: int | str | None = 2,
    source: str = "buddy_agent",
    payload: dict | list | str | None = None,
) -> uuid.UUID:
    payload_json = "{}" if payload is None else payload
    if not isinstance(payload_json, str):
        payload_json = json.dumps(payload_json)

    p_priority = _normalize_buddy_priority(priority)
    p_event_type = _normalize_buddy_event_type(event_type)

    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT public.record_buddy_event($1, $2, $3, $4, $5, $6, $7)",
            user_id if user_id else "system",
            p_event_type,
            title,
            body,
            p_priority,
            source,
            payload_json,
        )


async def _expire_pending_approvals(pool: asyncpg.Pool) -> None:
    try:
        async with pool.acquire() as conn:
            expired_rows = await conn.fetch(
                """
                UPDATE alpha_approval_queue
                SET status = 'expired'
                WHERE status = 'pending' AND expires_at < NOW()
                RETURNING id, actor_sub, description, risk_tier
                """
            )

            if not expired_rows:
                return

            expired_ids = [row["id"] for row in expired_rows]
            await conn.execute(
                """
                INSERT INTO alpha_approval_audit
                (approval_id, action_class, risk_tier, actor_sub, actor_type,
                 description, parameters_hash, nonce, decision, decided_by, overnight)
                SELECT q.id, q.action_class, q.risk_tier, q.actor_sub, q.actor_type,
                       q.description, q.parameters_hash, gen_random_uuid()::text, 'expired', 'system', false
                FROM alpha_approval_queue q
                WHERE q.id = ANY($1::uuid[])
                """,
                expired_ids,
            )

            count = len(expired_rows)
            comma_separated_ids = ",".join(
                str(expired_id) for expired_id in expired_ids
            )
            await _write_event(
                pool,
                user_id=None,
                event_type="system",
                title=f"{count} approval request(s) expired",
                body=f"Expired queue IDs: {comma_separated_ids}",
                priority=2,
            )
            logger.info("Expired %s pending approval(s)", count)
    except Exception:
        logger.error("Failed to expire pending approvals", exc_info=True)


async def _run_cycle(pool: asyncpg.Pool) -> None:
    new_trace_id()
    await _expire_pending_approvals(pool)

    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT DISTINCT user_id FROM alpha_conversation_memory"
        )

    for row in users:
        user_id = row["user_id"]

        try:
            async with pool.acquire() as conn:
                maintenance_result = await conn.fetchval(
                    "SELECT public.run_buddy_memory_maintenance($1)",
                    str(user_id),
                )

            await _write_event(
                pool,
                user_id=user_id,
                event_type="system",
                title="Memory maintenance complete",
                body="Completed per-user memory maintenance cycle.",
                priority=1,
                payload=maintenance_result,
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
                        pool,
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
