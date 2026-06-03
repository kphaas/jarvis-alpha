"""Scheduled Warden supervisor for Alpha security agents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg

from brain.agents.events import AgentEvent, emit_agent_event
from brain.agents.runtime import AgentRuntime, AgentRuntimeConfig
from brain.db.rls import platform_admin_connection

WARDEN_AGENT_ID = "warden"
DEFAULT_WARDEN_INTERVAL_SECONDS = 10 * 60
DEFAULT_MANAGED_AGENTS = (
    "porchlight",
    "keyturner",
    "sweep",
    "tripwire",
    "ledger",
)
STALE_SCHEDULED_RUN_SECONDS = 5 * 60
STALE_POSTURE_SWEEP_SECONDS = 30 * 60 * 60


@dataclass(frozen=True, slots=True)
class SupervisedAgent:
    agent_id: str
    display_name: str
    enabled: bool
    status: str
    cadence: str | None
    metadata: dict[str, Any]
    last_run_status: str | None = None
    last_run_at: datetime | None = None
    last_event_severity: str | None = None
    last_event_title: str | None = None
    last_event_at: datetime | None = None

    @property
    def role(self) -> str:
        role = self.metadata.get("warden_role")
        return role if isinstance(role, str) and role else "security_agent"


async def maybe_run_warden_supervisor(pool: asyncpg.Pool) -> bool:
    runtime = AgentRuntime(
        AgentRuntimeConfig(
            agent_id=WARDEN_AGENT_ID,
            trigger_type="scheduled",
            source="buddy",
        ),
        pool=pool,
    )
    state = await runtime.load_state()
    if state is None:
        return False
    interval = int(
        state.metadata.get(
            "supervision_interval_seconds", DEFAULT_WARDEN_INTERVAL_SECONDS
        )
    )
    if not await runtime.claim_due(interval_seconds=interval):
        return False

    async def _run(run_id: UUID) -> dict[str, Any]:
        return await collect_and_emit_warden_supervision(
            pool,
            run_id,
            state.metadata,
        )

    await runtime.run_once(_run)
    return True


async def collect_and_emit_warden_supervision(
    pool: asyncpg.Pool,
    run_id: UUID,
    warden_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_metadata = warden_metadata or {}
    managed_ids = managed_agent_ids(previous_metadata)
    agents = await load_supervised_agents(pool, managed_ids)
    now = datetime.now(timezone.utc)
    findings = supervision_findings(agents, now=now)
    snapshot = supervision_snapshot(agents, findings, checked_at=now)
    signature = supervision_signature(snapshot)
    previous_signature = str(previous_metadata.get("last_supervision_signature") or "")

    event_id: str | None = None
    if signature != previous_signature:
        result = await emit_agent_event(
            supervision_event(
                snapshot,
                run_id=run_id,
                previous_signature=previous_signature,
            ),
            pool=pool,
        )
        event_id = result.event_id

    runtime = AgentRuntime(
        AgentRuntimeConfig(
            agent_id=WARDEN_AGENT_ID,
            trigger_type="scheduled",
            source="buddy",
        ),
        pool=pool,
    )
    await runtime.update_metadata(
        {
            "last_supervision_checked_at": snapshot["checked_at"],
            "last_supervision_signature": signature,
            "last_supervision_status": snapshot["status"],
            "last_supervision_findings": snapshot["finding_count"],
            "last_supervision_event_id": event_id
            or previous_metadata.get("last_supervision_event_id"),
        }
    )
    return {"snapshot": snapshot, "event_id": event_id}


async def load_supervised_agents(
    pool: asyncpg.Pool,
    managed_ids: tuple[str, ...],
) -> list[SupervisedAgent]:
    async with platform_admin_connection(
        source="buddy",
        audit_actor=WARDEN_AGENT_ID,
        pool=pool,
    ) as conn:
        rows = await conn.fetch(
            """
            SELECT a.agent_id, a.display_name, a.enabled, a.status, a.cadence,
                   a.metadata,
                   lr.status AS last_run_status,
                   lr.last_run_at AS last_run_at,
                   le.severity AS last_event_severity,
                   le.title AS last_event_title,
                   le.created_at AS last_event_at
            FROM public.alpha_agents a
            LEFT JOIN LATERAL (
                SELECT status, COALESCE(completed_at, started_at, created_at) AS last_run_at
                FROM public.alpha_agent_runs
                WHERE agent_id = a.agent_id
                ORDER BY COALESCE(completed_at, started_at, created_at) DESC,
                         created_at DESC
                LIMIT 1
            ) lr ON TRUE
            LEFT JOIN LATERAL (
                SELECT severity, title, created_at
                FROM public.alpha_agent_events
                WHERE agent_id = a.agent_id
                ORDER BY created_at DESC
                LIMIT 1
            ) le ON TRUE
            WHERE a.agent_id = ANY($1::text[])
            ORDER BY array_position($1::text[], a.agent_id)
            """,
            list(managed_ids),
        )
    return [
        SupervisedAgent(
            agent_id=row["agent_id"],
            display_name=row["display_name"],
            enabled=bool(row["enabled"]),
            status=row["status"],
            cadence=row["cadence"],
            metadata=jsonb(row["metadata"]),
            last_run_status=row["last_run_status"],
            last_run_at=row["last_run_at"],
            last_event_severity=row["last_event_severity"],
            last_event_title=row["last_event_title"],
            last_event_at=row["last_event_at"],
        )
        for row in rows
    ]


def managed_agent_ids(metadata: dict[str, Any]) -> tuple[str, ...]:
    raw = metadata.get("managed_agents")
    if not isinstance(raw, list):
        return DEFAULT_MANAGED_AGENTS
    ids = tuple(str(value) for value in raw if str(value).strip())
    return ids or DEFAULT_MANAGED_AGENTS


def supervision_findings(
    agents: list[SupervisedAgent],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for agent in agents:
        if not agent.enabled or agent.status != "active":
            findings.append(
                finding(
                    agent,
                    severity="error",
                    code="agent_not_active",
                    detail=f"{agent.display_name} is not enabled and active.",
                )
            )
            continue

        if agent.last_event_severity in {"critical", "error"}:
            findings.append(
                finding(
                    agent,
                    severity="error",
                    code="last_event_error",
                    detail=agent.last_event_title or "Latest agent event is an error.",
                )
            )
        elif agent.last_event_severity in {"warning", "needs_input"}:
            findings.append(
                finding(
                    agent,
                    severity="warning",
                    code="last_event_attention",
                    detail=agent.last_event_title
                    or "Latest agent event requires attention.",
                )
            )

        stale = stale_reason(agent, now=now)
        if stale:
            findings.append(
                finding(
                    agent,
                    severity="warning",
                    code=stale["code"],
                    detail=stale["detail"],
                )
            )
    return findings


def stale_reason(agent: SupervisedAgent, *, now: datetime) -> dict[str, str] | None:
    if agent.role == "network_sweep":
        if agent.last_run_at is None:
            return {
                "code": "scheduled_agent_never_ran",
                "detail": f"{agent.display_name} has not recorded a run.",
            }
        age_seconds = (now - as_aware(agent.last_run_at)).total_seconds()
        if age_seconds > STALE_SCHEDULED_RUN_SECONDS:
            return {
                "code": "scheduled_agent_stale",
                "detail": f"{agent.display_name} last ran {int(age_seconds)}s ago.",
            }
    if agent.role == "posture_sweep":
        last_seen = agent.last_run_at or agent.last_event_at
        if last_seen is None:
            return {
                "code": "posture_sweep_never_seen",
                "detail": f"{agent.display_name} has no run or event history.",
            }
        age_seconds = (now - as_aware(last_seen)).total_seconds()
        if age_seconds > STALE_POSTURE_SWEEP_SECONDS:
            return {
                "code": "posture_sweep_stale",
                "detail": f"{agent.display_name} last checked in {int(age_seconds)}s ago.",
            }
    return None


def supervision_snapshot(
    agents: list[SupervisedAgent],
    findings: list[dict[str, Any]],
    *,
    checked_at: datetime,
) -> dict[str, Any]:
    severity = highest_severity(findings)
    healthy_agents = [
        agent.agent_id
        for agent in agents
        if not any(finding["agent_id"] == agent.agent_id for finding in findings)
    ]
    return {
        "checked_at": checked_at.isoformat(),
        "status": "pass" if not findings else severity,
        "managed_count": len(agents),
        "healthy_count": len(healthy_agents),
        "finding_count": len(findings),
        "findings": findings,
        "healthy_agents": healthy_agents,
    }


def supervision_signature(snapshot: dict[str, Any]) -> str:
    stable = {
        "status": snapshot["status"],
        "findings": [
            {
                "agent_id": finding["agent_id"],
                "code": finding["code"],
                "severity": finding["severity"],
            }
            for finding in snapshot["findings"]
        ],
    }
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def supervision_event(
    snapshot: dict[str, Any],
    *,
    run_id: UUID,
    previous_signature: str,
) -> AgentEvent:
    status = snapshot["status"]
    if status == "pass":
        title = "Warden security crew recovered"
        message = (
            f"{snapshot['healthy_count']}/{snapshot['managed_count']} managed "
            "security agents are healthy."
        )
        severity = "info"
    else:
        title = "Warden security crew needs attention"
        message = "; ".join(
            f"{finding['display_name']}: {finding['detail']}"
            for finding in snapshot["findings"][:4]
        )
        severity = "critical" if status == "error" else "warning"
    return AgentEvent(
        agent_id=WARDEN_AGENT_ID,
        run_id=run_id,
        event_type="warden.supervision",
        title=title,
        message=message,
        severity=severity,
        channel_key="security_alerts",
        payload={
            "snapshot": snapshot,
            "previous_signature": previous_signature or None,
        },
        correlation_id=f"warden:supervision:{supervision_signature(snapshot)}",
    )


def finding(
    agent: SupervisedAgent,
    *,
    severity: str,
    code: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "agent_id": agent.agent_id,
        "display_name": agent.display_name,
        "role": agent.role,
        "severity": severity,
        "code": code,
        "detail": detail,
    }


def highest_severity(findings: list[dict[str, Any]]) -> str:
    if any(finding["severity"] == "error" for finding in findings):
        return "error"
    if any(finding["severity"] == "warning" for finding in findings):
        return "warning"
    return "pass"


def as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def jsonb(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)
