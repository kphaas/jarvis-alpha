"""Scheduled ChatOps smoke monitor."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from brain.agents.events import AgentEvent, emit_agent_event
from brain.agents.runtime import AgentRuntime, AgentRuntimeConfig
from brain.db.rls import platform_admin_connection

CHATOPS_SMOKE_AGENT_ID = "chatops_smoke"
DEFAULT_SMOKE_INTERVAL_SECONDS = 6 * 60 * 60


async def maybe_run_chatops_smoke(pool: asyncpg.Pool) -> bool:
    runtime = AgentRuntime(
        AgentRuntimeConfig(
            agent_id=CHATOPS_SMOKE_AGENT_ID,
            trigger_type="scheduled",
            source="buddy",
        ),
        pool=pool,
    )
    state = await runtime.load_state()
    if state is None:
        return False
    interval = int(
        state.metadata.get("smoke_interval_seconds", DEFAULT_SMOKE_INTERVAL_SECONDS)
    )
    if not await runtime.claim_due(interval_seconds=interval):
        return False

    await runtime.run_once(lambda run_id: _emit_smoke_event(pool, run_id))
    return True


async def run_chatops_smoke_now(pool: asyncpg.Pool):
    runtime = AgentRuntime(
        AgentRuntimeConfig(
            agent_id=CHATOPS_SMOKE_AGENT_ID,
            trigger_type="manual",
            source="http",
        ),
        pool=pool,
    )
    return await runtime.run_once(lambda run_id: _emit_smoke_event(pool, run_id))


async def _emit_smoke_event(pool: asyncpg.Pool, run_id: UUID) -> dict[str, Any]:
    snapshot = await collect_chatops_health(pool)
    title = "Alpha ChatOps smoke"
    message = format_chatops_smoke_message(snapshot)
    severity = "warning" if snapshot["failed_notifications_24h"] else "info"

    result = await emit_agent_event(
        AgentEvent(
            agent_id=CHATOPS_SMOKE_AGENT_ID,
            run_id=run_id,
            event_type="chatops.smoke",
            title=title,
            message=message,
            severity=severity,
            channel_key="alpha_events",
            payload=snapshot,
            correlation_id=f"chatops_smoke:{snapshot['checked_at']}",
        ),
        pool=pool,
    )
    return {"event_id": result.event_id, "snapshot": snapshot}


async def collect_chatops_health(pool: asyncpg.Pool) -> dict[str, Any]:
    async with platform_admin_connection(
        source="buddy",
        audit_actor=CHATOPS_SMOKE_AGENT_ID,
        pool=pool,
    ) as conn:
        row = await conn.fetchrow(
            """
            SELECT
                NOW()::text AS checked_at,
                COUNT(*) FILTER (WHERE status = 'active') AS active_agents,
                COUNT(*) FILTER (WHERE enabled) AS enabled_agents,
                COUNT(*) AS total_agents
            FROM public.alpha_agents
            """
        )
        events = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE notification_status = 'failed'
                      AND created_at >= NOW() - INTERVAL '24 hours'
                ) AS failed_notifications_24h,
                COUNT(*) FILTER (
                    WHERE notification_status IN ('pending', 'not_requested')
                      AND created_at >= NOW() - INTERVAL '24 hours'
                ) AS pending_notifications_24h
            FROM public.alpha_agent_events
            """
        )
        approvals = await conn.fetchrow(
            """
            SELECT COUNT(*) AS pending_approvals
            FROM public.alpha_approval_queue
            WHERE status = 'pending'
              AND expires_at > NOW()
            """
        )

    return {
        "checked_at": row["checked_at"],
        "active_agents": int(row["active_agents"] or 0),
        "enabled_agents": int(row["enabled_agents"] or 0),
        "total_agents": int(row["total_agents"] or 0),
        "failed_notifications_24h": int(events["failed_notifications_24h"] or 0),
        "pending_notifications_24h": int(events["pending_notifications_24h"] or 0),
        "pending_approvals": int(approvals["pending_approvals"] or 0),
    }


def format_chatops_smoke_message(snapshot: dict[str, Any]) -> str:
    return (
        "ChatOps path is live. "
        f"Agents {snapshot['enabled_agents']}/{snapshot['active_agents']} enabled, "
        f"pending approvals {snapshot['pending_approvals']}, "
        f"notification failures 24h {snapshot['failed_notifications_24h']}."
    )
