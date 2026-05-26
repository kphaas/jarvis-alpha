"""Reusable runtime kit for managed Alpha agents."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import asyncpg

from brain.db.rls import platform_admin_connection
from jarvis_common.logging_config import get_logger, new_trace_id

logger = get_logger("alpha_agents")

AgentRunStatus = Literal["succeeded", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig:
    agent_id: str
    trigger_type: str = "scheduled"
    source: Literal["scheduled", "buddy", "watchdog", "executor", "dream", "test"] = (
        "scheduled"
    )
    audit_actor: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRuntimeState:
    agent_id: str
    status: str
    enabled: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def runnable(self) -> bool:
        return self.enabled and self.status == "active"


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    agent_id: str
    executed: bool
    run_id: UUID | None = None
    status: AgentRunStatus | None = None
    trace_id: str | None = None
    output: Any = None
    skipped_reason: str | None = None
    error_text: str | None = None


AgentOperation = Callable[[UUID], Awaitable[Any] | Any]


class AgentRuntime:
    """Small runtime wrapper for run ledger, status checks, and metadata."""

    def __init__(self, config: AgentRuntimeConfig, *, pool: asyncpg.Pool) -> None:
        self.config = config
        self.pool = pool

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    @property
    def audit_actor(self) -> str:
        return self.config.audit_actor or self.config.agent_id

    async def load_state(self) -> AgentRuntimeState | None:
        async with platform_admin_connection(
            source=self.config.source,
            audit_actor=self.audit_actor,
            pool=self.pool,
        ) as conn:
            row = await conn.fetchrow(
                """
                SELECT agent_id, status, enabled, metadata
                FROM public.alpha_agents
                WHERE agent_id = $1
                """,
                self.agent_id,
            )

        if not row:
            return None
        return AgentRuntimeState(
            agent_id=row["agent_id"],
            status=row["status"],
            enabled=bool(row["enabled"]),
            metadata=_jsonb(row["metadata"]),
        )

    async def claim_due(self, *, interval_seconds: int) -> bool:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

        async with platform_admin_connection(
            source=self.config.source,
            audit_actor=self.audit_actor,
            pool=self.pool,
        ) as conn:
            return bool(
                await conn.fetchval(
                    "SELECT public.claim_agent_due_run($1, $2)",
                    self.agent_id,
                    interval_seconds,
                )
            )

    async def start_run(
        self,
        *,
        trace_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> UUID:
        async with platform_admin_connection(
            source=self.config.source,
            audit_actor=self.audit_actor,
            pool=self.pool,
        ) as conn:
            return await conn.fetchval(
                "SELECT public.start_agent_run($1, $2, $3, $4::jsonb)",
                self.agent_id,
                self.config.trigger_type,
                trace_id,
                json.dumps(dict(metadata or {})),
            )

    async def finish_run(
        self,
        run_id: UUID,
        *,
        status: AgentRunStatus,
        cost_usd: Decimal = Decimal("0"),
        error_text: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        async with platform_admin_connection(
            source=self.config.source,
            audit_actor=self.audit_actor,
            pool=self.pool,
        ) as conn:
            await conn.execute(
                "SELECT public.finish_agent_run($1, $2, $3, $4, $5::jsonb)",
                run_id,
                status,
                cost_usd,
                error_text,
                json.dumps(dict(metadata or {})),
            )

    async def update_metadata(self, metadata: Mapping[str, Any]) -> None:
        async with platform_admin_connection(
            source=self.config.source,
            audit_actor=self.audit_actor,
            pool=self.pool,
        ) as conn:
            await conn.execute(
                "SELECT public.update_agent_runtime_metadata($1, $2::jsonb)",
                self.agent_id,
                json.dumps(dict(metadata)),
            )

    async def run_once(
        self,
        operation: AgentOperation,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentRunResult:
        state = await self.load_state()
        trace_id = new_trace_id()

        if state is None:
            logger.warning("agent_runtime_unknown agent_id=%s", self.agent_id)
            return AgentRunResult(
                agent_id=self.agent_id,
                executed=False,
                trace_id=trace_id,
                skipped_reason="unknown_agent",
            )
        if not state.runnable:
            return AgentRunResult(
                agent_id=self.agent_id,
                executed=False,
                trace_id=trace_id,
                skipped_reason="agent_not_runnable",
            )

        run_id = await self.start_run(trace_id=trace_id, metadata=metadata)
        try:
            output = operation(run_id)
            if inspect.isawaitable(output):
                output = await output
        except Exception as exc:
            await self.finish_run(
                run_id,
                status="failed",
                error_text=str(exc),
                metadata={"exception_type": type(exc).__name__},
            )
            raise

        await self.finish_run(run_id, status="succeeded")
        return AgentRunResult(
            agent_id=self.agent_id,
            executed=True,
            run_id=run_id,
            status="succeeded",
            trace_id=trace_id,
            output=output,
        )


def _jsonb(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)
