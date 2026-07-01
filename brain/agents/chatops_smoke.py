"""Scheduled ChatOps smoke monitor."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from brain.agents.events import AgentEvent, emit_agent_event
from brain.agents.runtime import AgentRuntime, AgentRuntimeConfig
from brain.db.rls import platform_admin_connection
from brain.services.agent_workspace import WorkspacePathError, get_workspace_backend
from jarvis_common.logging_config import get_logger

CHATOPS_SMOKE_AGENT_ID = "chatops_smoke"
DEFAULT_SMOKE_INTERVAL_SECONDS = 6 * 60 * 60
_WORKSPACE_ARTIFACT_PATH = "outputs/chatops_smoke_snapshot.json"
_WORKSPACE_ARTIFACT_KIND = "chatops.smoke.snapshot"

logger = get_logger("alpha_agents")


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
    artifact = None
    artifact_error = None
    try:
        artifact = await _persist_workspace_snapshot_artifact(pool, run_id, snapshot)
    except Exception as exc:
        artifact_error = str(exc)
        logger.warning(
            "chatops_smoke_workspace_artifact_failed run_id=%s error=%s",
            run_id,
            artifact_error,
        )
    return {
        "event_id": result.event_id,
        "snapshot": snapshot,
        "artifact": artifact,
        "artifact_error": artifact_error,
    }


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


async def _persist_workspace_snapshot_artifact(
    pool: asyncpg.Pool,
    run_id: UUID,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    backend = get_workspace_backend()
    async with platform_admin_connection(
        source="buddy",
        audit_actor=CHATOPS_SMOKE_AGENT_ID,
        pool=pool,
    ) as conn:
        row = await conn.fetchrow(
            """
            SELECT id, agent_id, created_at, workspace_backend, workspace_root,
                   policy_labels, approval_scope, retention_class
            FROM public.alpha_agent_runs
            WHERE id = $1
            """,
            run_id,
        )
        if not row:
            raise RuntimeError(f"agent run not found: {run_id}")

        try:
            manifest = backend.init_workspace(
                row["id"],
                row["agent_id"],
                _jsonb_list(row["policy_labels"]),
                row["approval_scope"],
                row["retention_class"],
                workspace_root=str(row["workspace_root"] or "").strip() or None,
                created_at=row["created_at"],
            )
        except WorkspacePathError as exc:
            raise RuntimeError(str(exc)) from exc

        if (
            row["workspace_root"] != manifest.workspace_root
            or row["workspace_backend"] != manifest.workspace_backend
        ):
            await conn.execute(
                """
                UPDATE public.alpha_agent_runs
                SET workspace_backend = $2,
                    workspace_root = $3
                WHERE id = $1
                """,
                row["id"],
                manifest.workspace_backend,
                manifest.workspace_root,
            )

        document = (
            json.dumps(
                {
                    "agent_id": CHATOPS_SMOKE_AGENT_ID,
                    "run_id": str(run_id),
                    "snapshot": snapshot,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        staged = backend.stage_text(
            run_id,
            _WORKSPACE_ARTIFACT_PATH,
            document,
            _WORKSPACE_ARTIFACT_KIND,
            content_type="application/json",
            policy_labels=_jsonb_list(row["policy_labels"]),
            workspace_root=manifest.workspace_root,
        )
        try:
            await conn.execute(
                """
                INSERT INTO public.alpha_agent_run_artifacts
                    (id, run_id, agent_id, relative_path, kind, content_type, size_bytes,
                     sha256, policy_labels)
                VALUES
                    ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb)
                """,
                staged.record.artifact_id,
                staged.record.run_id,
                row["agent_id"],
                staged.record.relative_path,
                staged.record.kind,
                staged.record.content_type,
                staged.record.size_bytes,
                staged.record.sha256,
                json.dumps(list(staged.record.policy_labels)),
            )
            record = backend.commit_staged_artifact(staged)
        except Exception:
            await conn.execute(
                "DELETE FROM public.alpha_agent_run_artifacts WHERE id = $1::uuid",
                staged.record.artifact_id,
            )
            backend.cleanup_staged_artifact(staged)
            raise
    return record.to_dict()


def _jsonb_list(value: object) -> list[str]:
    if value is None:
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]
