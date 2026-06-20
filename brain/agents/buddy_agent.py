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
from brain.db.rls import platform_admin_connection
from brain.services.temporal_storage_monitor import (
    collect_temporal_storage_snapshot,
    temporal_storage_summary_body,
)
from brain.services.memory_consolidation import (
    collect_memory_consolidation_report,
    memory_consolidation_summary_body,
)
from brain.services.spark_memory_grounding import collect_spark_memory_grounding_status
from brain.services.spark_personality_memory import (
    collect_spark_personality_memory_status,
    fetch_personality_memory,
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
_last_spark_memory_day_key: str | None = None
_last_memory_consolidation_day_key: str | None = None


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


def _decode_memory_maintenance_payload(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _maintenance_errors(payload: dict[str, object]) -> list[object]:
    errors = payload.get("errors")
    return errors if isinstance(errors, list) else []


def memory_maintenance_changed_count(value: object) -> int:
    """Return row-change count from the DB maintenance payload."""

    payload = _decode_memory_maintenance_payload(value)
    total = 0
    for key in (
        "evicted_working",
        "evicted_episodic",
        "capped_episodic",
        "capped_semantic",
        "promoted",
    ):
        try:
            total += max(0, int(payload.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return total


def should_write_memory_maintenance_event(value: object) -> bool:
    """Suppress no-op per-minute maintenance rows; preserve changes/errors."""

    payload = _decode_memory_maintenance_payload(value)
    return (
        bool(_maintenance_errors(payload))
        or memory_maintenance_changed_count(payload) > 0
    )


def memory_maintenance_event_priority(value: object) -> int:
    payload = _decode_memory_maintenance_payload(value)
    return 3 if _maintenance_errors(payload) else 1


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


def spark_memory_summary_body(
    status: dict[str, object],
    personality_status: dict[str, object] | None = None,
) -> str:
    """Human-safe Buddy summary of the Spark persona grounding lane."""

    principal = str(status.get("principal_id") or "unknown")
    state = str(status.get("status") or "unknown")
    proposal_suffix = ""
    if personality_status:
        proposal_suffix = (
            " Spark memory proposals waiting for review: "
            f"{int(personality_status.get('proposal_count') or 0)}."
        )
    if state == "ok":
        feedback_count = int(status.get("feedback_count") or 0)
        line_count = int(status.get("line_count") or 0)
        return (
            f"Spark persona grounding is available for {principal}. "
            f"Runtime context lines: {line_count}. "
            f"Draft-edit feedback waiting for review: {feedback_count}."
            f"{proposal_suffix}"
        )
    if state == "skipped":
        return f"Spark persona grounding skipped for {principal}.{proposal_suffix}"
    error_class = str(status.get("error_class") or "unknown_error")
    return (
        f"Spark persona grounding is unavailable for {principal}. "
        f"Error class: {error_class}.{proposal_suffix}"
    )


async def _maybe_write_spark_memory_summary(pool: asyncpg.Pool) -> None:
    global _last_spark_memory_day_key

    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    if _last_spark_memory_day_key == day_key:
        return

    try:
        status = collect_spark_memory_grounding_status(principal_id="ken")
        existing_rows: list[dict[str, object]] = []
        try:
            async with platform_admin_connection(
                source="buddy",
                audit_actor="buddy:spark_memory_summary",
                pool=pool,
            ) as conn:
                existing_rows = await fetch_personality_memory(conn, "ken")
        except Exception as exc:
            logger.warning("spark personality memory rows unavailable: %s", exc)
        personality_status = collect_spark_personality_memory_status(
            principal_id="ken",
            existing_rows=existing_rows,
        )
        priority = 1 if status.get("status") in {"ok", "skipped"} else 3
        await _write_event(
            pool,
            user_id="system",
            event_type="alert" if priority == 3 else "system",
            title="Spark memory grounding status",
            body=spark_memory_summary_body(status, personality_status),
            priority=priority,
            source="spark_memory_grounding",
            payload={
                "day_key": day_key,
                "principal_id": status.get("principal_id"),
                "status": status.get("status"),
                "line_count": status.get("line_count"),
                "feedback_count": status.get("feedback_count"),
                "error_class": status.get("error_class"),
                "personality_active_count": personality_status.get("active_count"),
                "personality_proposal_count": personality_status.get("proposal_count"),
                "feedback_phrase_count": personality_status.get(
                    "feedback_phrase_count"
                ),
            },
        )
        _last_spark_memory_day_key = day_key
    except Exception as exc:
        logger.warning("spark memory summary failed: %s", exc)


async def _maybe_write_memory_consolidation_summary(pool: asyncpg.Pool) -> None:
    global _last_memory_consolidation_day_key

    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    if _last_memory_consolidation_day_key == day_key:
        return

    try:
        reports: list[dict[str, object]] = []
        async with platform_admin_connection(
            source="buddy",
            audit_actor="buddy:memory_consolidation_summary",
            pool=pool,
        ) as conn:
            users = await conn.fetch(
                "SELECT unnest(public.list_active_memory_users()) AS user_id"
            )
            for row in users:
                report = await collect_memory_consolidation_report(
                    conn,
                    str(row["user_id"]),
                )
                reports.append(report)

        if not reports:
            return

        total_candidates = sum(
            int(report.get("candidate_count") or 0) for report in reports
        )
        total_blocked = sum(
            int(report.get("blocked_candidate_count") or 0) for report in reports
        )
        if len(reports) == 1:
            body = memory_consolidation_summary_body(reports[0])
        else:
            body = (
                "Dream memory consolidation backlog across "
                f"{len(reports)} users: {total_candidates} review candidates. "
                f"Blocked suspicious candidates: {total_blocked}. "
                "Planner writes are disabled; executable proposals require T5 review."
            )
        priority = 2 if total_candidates else 1
        await _write_event(
            pool,
            user_id="system",
            event_type="system",
            title="Dream memory consolidation backlog",
            body=body,
            priority=priority,
            source="memory_consolidation",
            payload={
                "day_key": day_key,
                "user_count": len(reports),
                "candidate_count": total_candidates,
                "blocked_candidate_count": total_blocked,
                "write_actions_enabled": False,
                "users": [
                    {
                        "user_id": report.get("user_id"),
                        "canonical_user_id": report.get("canonical_user_id"),
                        "status": report.get("status"),
                        "candidate_count": report.get("candidate_count"),
                        "blocked_candidate_count": report.get(
                            "blocked_candidate_count"
                        ),
                        "promotion_count": len(
                            report.get("promotion_candidates") or []
                        ),
                        "duplicate_count": len(
                            report.get("semantic_duplicate_groups") or []
                        ),
                        "decay_count": len(report.get("decay_candidates") or []),
                        "procedural_count": len(
                            report.get("procedural_candidates") or []
                        ),
                    }
                    for report in reports
                ],
            },
        )
        _last_memory_consolidation_day_key = day_key
    except Exception as exc:
        logger.warning("memory consolidation summary failed: %s", exc)


async def _run_cycle(pool: asyncpg.Pool) -> None:
    new_trace_id()
    await _expire_pending_approvals(pool)
    await _maybe_write_temporal_storage_summary(pool)
    await _maybe_write_spark_memory_summary(pool)
    await _maybe_write_memory_consolidation_summary(pool)
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

            if should_write_memory_maintenance_event(maintenance_result):
                priority = memory_maintenance_event_priority(maintenance_result)
                changed = memory_maintenance_changed_count(maintenance_result)
                await _write_event(
                    pool,
                    user_id=user_id,
                    event_type="alert" if priority >= 3 else "system",
                    title="Memory maintenance changed rows",
                    body=f"Memory maintenance changed {changed} row(s).",
                    priority=priority,
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
