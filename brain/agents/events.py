"""Durable AgentEvent contract and ChatOps delivery.

Agents should persist an event before trying to notify Mattermost. Mattermost is
the operator surface, not the internal coordination bus; the database remains
the system of record.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

import asyncpg
from pydantic import BaseModel, Field, field_validator

from brain.db.pool import get_pool
from brain.db.rls import platform_admin_connection
from brain.skills.notify import notify_skill_handlers
from brain.skills.policy_gate import SkillInvocation, SkillPolicyGate
from brain.skills.runner import SkillCall
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

AgentEventSeverity = Literal[
    "debug",
    "info",
    "needs_input",
    "warning",
    "error",
    "critical",
]

MattermostSource = Literal["alpha", "watchdog"]

_CHANNEL_BY_SEVERITY = {
    "needs_input": "needs_input",
    "error": "alerts",
    "critical": "alerts",
}


class AgentEvent(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    event_type: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[a-z][a-z0-9_]*(?:[._][a-z][a-z0-9_]*)*$",
    )
    title: str = Field(min_length=1, max_length=250)
    message: str = Field(min_length=1, max_length=4000)
    severity: AgentEventSeverity = "info"
    payload: dict[str, Any] = Field(default_factory=dict)
    run_id: UUID | None = None
    correlation_id: str = Field(default_factory=lambda: uuid4().hex, max_length=128)
    channel_key: str = Field(
        default="alpha_events",
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_]{0,31}$",
    )
    mattermost_source: MattermostSource = "alpha"
    notify: bool = True

    @field_validator("channel_key", mode="before")
    @classmethod
    def normalize_channel_key(cls, value: str) -> str:
        return str(value).strip().lstrip("#").replace("-", "_")

    @property
    def routed_channel_key(self) -> str:
        return _CHANNEL_BY_SEVERITY.get(self.severity, self.channel_key)

    def notify_payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "source": self.mattermost_source,
            "channel_key": self.channel_key,
        }


class AgentEventResult(BaseModel):
    event_id: str
    notification_status: str
    notification_result: dict[str, Any] = Field(default_factory=dict)


async def emit_agent_event(
    event: AgentEvent,
    *,
    pool: asyncpg.Pool | None = None,
    raise_on_notify_failure: bool = False,
) -> AgentEventResult:
    """Persist an AgentEvent and optionally deliver it through ``notify.send``.

    Notification failures are recorded on the event by default. Callers should
    opt into raising only when the notification itself is the requested action.
    """

    pool = pool or get_pool()
    if pool is None:
        raise RuntimeError("no DB pool available for agent event")

    event_id = await _record_event(pool, event)
    if not event.notify:
        await _mark_notification(
            pool,
            event_id,
            status="skipped",
            result={"reason": "event_notify_false"},
        )
        return AgentEventResult(event_id=str(event_id), notification_status="skipped")

    try:
        decision = await _evaluate_notify_policy(pool, event, event_id)
        if not decision.allowed:
            result = {
                "reason": decision.reason,
                "outcome": decision.outcome,
                "skill_name": decision.skill_name,
            }
            await _mark_notification(
                pool,
                event_id,
                status="denied",
                result=result,
                error=decision.reason,
            )
            return AgentEventResult(
                event_id=str(event_id),
                notification_status="denied",
                notification_result=result,
            )

        handler = notify_skill_handlers()["notify.send"]
        output = await handler(
            SkillCall(
                invocation=_notify_invocation(event, event_id),
                decision=decision,
                payload=event.notify_payload(),
            )
        )
        status = "fallback_sent" if output.get("fallback_used") else "sent"
        await _mark_notification(pool, event_id, status=status, result=output)
        return AgentEventResult(
            event_id=str(event_id),
            notification_status=status,
            notification_result=dict(output),
        )
    except Exception as exc:
        logger.error(
            "AGENT_EVENT_NOTIFY_FAILED agent_id=%s event_type=%s event_id=%s error=%s",
            event.agent_id,
            event.event_type,
            event_id,
            exc,
            exc_info=True,
        )
        await _mark_notification(
            pool,
            event_id,
            status="failed",
            result={"provider": "notify.send"},
            error=str(exc),
        )
        if raise_on_notify_failure:
            raise
        return AgentEventResult(event_id=str(event_id), notification_status="failed")


async def _record_event(pool: asyncpg.Pool, event: AgentEvent) -> UUID:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT public.record_agent_event(
                $1, $2, $3, $4, $5, $6::jsonb, $7::uuid, $8, $9, $10
            )
            """,
            event.agent_id,
            event.event_type,
            event.title,
            event.message,
            event.severity,
            json.dumps(event.payload, default=str),
            str(event.run_id) if event.run_id else None,
            event.correlation_id,
            event.routed_channel_key,
            "pending" if event.notify else "not_requested",
        )


async def _mark_notification(
    pool: asyncpg.Pool,
    event_id: UUID,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            SELECT public.mark_agent_event_notification($1::uuid, $2, $3::jsonb, $4)
            """,
            str(event_id),
            status,
            json.dumps(result or {}, default=str),
            error,
        )


async def _evaluate_notify_policy(
    pool: asyncpg.Pool,
    event: AgentEvent,
    event_id: UUID,
):
    async with platform_admin_connection(
        source="scheduled",
        audit_actor=event.agent_id,
        pool=pool,
    ) as conn:
        return await SkillPolicyGate().evaluate(
            conn, _notify_invocation(event, event_id)
        )


def _notify_invocation(event: AgentEvent, event_id: UUID) -> SkillInvocation:
    return SkillInvocation(
        agent_id=event.agent_id,
        skill_name="notify.send",
        estimated_cost_usd=Decimal("0"),
        idempotency_key=f"agent-event:{event_id}",
    )
