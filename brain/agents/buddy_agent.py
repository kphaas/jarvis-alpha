from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import asyncpg

from brain.agents.events import AgentEvent, emit_agent_event
from brain.agents.chatops_smoke import maybe_run_chatops_smoke
from brain.agents.network_watchdog import maybe_run_network_watchdog
from brain.agents.porchlight import maybe_run_porchlight
from brain.agents.warden import maybe_run_warden_supervisor
from brain.services.temporal_storage_monitor import (
    collect_temporal_storage_snapshot,
    temporal_storage_summary_body,
)
from jarvis_common.logging_config import get_logger, new_trace_id

logger = get_logger("alpha_buddy")

BUDDY_INTERVAL = int(os.environ.get("BUDDY_INTERVAL_SECONDS", "60"))
ALERT_THRESHOLD_HOURS = 20
TEMPORAL_STORAGE_SUMMARY_WEEKDAY = int(
    os.environ.get("TEMPORAL_STORAGE_SUMMARY_WEEKDAY", "0")
)

_VALID_BUDDY_EVENT_TYPES = frozenset({"alert", "reminder", "suggestion", "system"})
_last_temporal_storage_week_key: str | None = None


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


def _payload_for_agent_event(payload_json: str):
    try:
        return json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return {"raw": str(payload_json)}


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
        event_id = await conn.fetchval(
            "SELECT public.record_buddy_event($1, $2, $3, $4, $5, $6, $7)",
            user_id if user_id else "system",
            p_event_type,
            title,
            body,
            p_priority,
            source,
            payload_json,
        )
    if p_priority >= 3 or p_event_type == "alert":
        try:
            await emit_agent_event(
                AgentEvent(
                    agent_id="buddy",
                    event_type=f"buddy.{p_event_type}",
                    title=title,
                    message=body or title,
                    severity="warning" if p_priority < 4 else "critical",
                    payload={
                        "buddy_event_id": str(event_id),
                        "source": source,
                        "user_id": user_id or "system",
                        "payload": _payload_for_agent_event(payload_json),
                    },
                    correlation_id=f"buddy:{event_id}",
                ),
                pool=pool,
            )
        except Exception:
            logger.error("buddy agent event notify failed", exc_info=True)

    return event_id


# TD: alpha_approval_queue/audit writes are bare DML. Wrap in SECDEF when those
# tables get FORCE RLS. See Stage 5c handoff.
async def _expire_pending_approvals(pool: asyncpg.Pool) -> None:
    try:
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT public.expire_pending_approvals()")
            if count:
                logger.info("buddy_expire_approvals expired=%d", count)
    except Exception as exc:
        logger.warning("buddy_expire_approvals error: %s", exc)


async def _maybe_write_temporal_storage_summary(pool: asyncpg.Pool) -> None:
    global _last_temporal_storage_week_key

    now = datetime.now(timezone.utc)
    if now.weekday() != TEMPORAL_STORAGE_SUMMARY_WEEKDAY:
        return

    week_key = now.strftime("%G-W%V")
    if _last_temporal_storage_week_key == week_key:
        return

    try:
        snapshot = await collect_temporal_storage_snapshot(include_row_counts=True)
        priority = 3 if snapshot["status"] in {"alert", "degraded"} else 1
        await _write_event(
            pool,
            user_id="system",
            event_type="alert" if priority == 3 else "system",
            title="Temporal storage weekly summary",
            body=temporal_storage_summary_body(snapshot),
            priority=priority,
            source="temporal_storage_monitor",
            payload={
                "week_key": week_key,
                "status": snapshot["status"],
                "temporal_total_bytes": snapshot["temporal_total_bytes"],
                "disk_free_bytes": snapshot["disk_free_bytes"],
                "threshold_bytes": snapshot["threshold_bytes"],
                "threshold_exceeded": snapshot["threshold_exceeded"],
                "databases": snapshot["databases"],
                "errors": snapshot["errors"],
            },
        )
        _last_temporal_storage_week_key = week_key
    except Exception as exc:
        logger.warning("temporal storage weekly summary failed: %s", exc)


async def _run_cycle(pool: asyncpg.Pool) -> None:
    new_trace_id()
    await _expire_pending_approvals(pool)
    await _maybe_write_temporal_storage_summary(pool)
    await _maybe_run_managed_agents(pool)

    async with pool.acquire() as conn:
        users = await conn.fetch(
            "SELECT unnest(public.list_active_memory_users()) AS user_id"
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
                aging = await conn.fetch(
                    "SELECT id, summary FROM public.get_buddy_promotion_candidates($1)",
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


async def _maybe_run_managed_agents(pool: asyncpg.Pool) -> None:
    for runner in (
        maybe_run_chatops_smoke,
        maybe_run_network_watchdog,
        maybe_run_porchlight,
        maybe_run_warden_supervisor,
    ):
        try:
            await runner(pool)
        except Exception as exc:
            logger.warning("managed agent runner failed: %s", exc)


async def run_buddy() -> None:
    logger.info("Buddy agent starting — interval %ss", BUDDY_INTERVAL)

    from brain.core.config import ALPHA_DB_DSN_BUDDY

    pool = await asyncpg.create_pool(ALPHA_DB_DSN_BUDDY, min_size=1, max_size=3)
    logger.info("Buddy DB pool ready")

    while True:
        try:
            await _run_cycle(pool)
        except Exception as e:
            logger.error("Buddy top-level error: %s", e)

        await asyncio.sleep(BUDDY_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(run_buddy())
    except Exception as exc:
        logger.error(
            "Buddy agent crashed — unhandled exception: %s",
            exc,
            exc_info=True,
        )
        raise
