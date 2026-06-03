"""Manual agent run dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import asyncpg

from brain.agents.chatops_smoke import (
    CHATOPS_SMOKE_AGENT_ID,
    run_chatops_smoke_now,
)
from brain.agents.network_watchdog import (
    NETWORK_WATCHDOG_AGENT_ALIAS,
    NETWORK_WATCHDOG_AGENT_ID,
    run_network_watchdog_now,
)
from brain.agents.porchlight import PORCHLIGHT_AGENT_ID, run_porchlight_now
from brain.agents.runtime import AgentRunResult

ManualRunner = Callable[[asyncpg.Pool], Awaitable[AgentRunResult]]

MANUAL_RUNNERS: dict[str, ManualRunner] = {
    CHATOPS_SMOKE_AGENT_ID: run_chatops_smoke_now,
    NETWORK_WATCHDOG_AGENT_ID: run_network_watchdog_now,
    PORCHLIGHT_AGENT_ID: run_porchlight_now,
}
AGENT_ALIASES = {
    NETWORK_WATCHDOG_AGENT_ALIAS: NETWORK_WATCHDOG_AGENT_ID,
}

LOW_RISK_MANUAL_TIERS = {"T1", "T2"}


@dataclass(frozen=True, slots=True)
class ManualRunEligibility:
    allowed: bool
    reason: str


async def run_agent_now(agent_id: str, *, pool: asyncpg.Pool) -> AgentRunResult:
    runner = MANUAL_RUNNERS.get(canonical_agent_id(agent_id))
    if runner is None:
        raise ValueError("manual_runner_not_registered")
    return await runner(pool)


def canonical_agent_id(agent_id: str) -> str:
    return AGENT_ALIASES.get(agent_id, agent_id)


def manual_run_eligibility(agent_row: Mapping[str, Any] | None) -> ManualRunEligibility:
    if not agent_row:
        return ManualRunEligibility(False, "unknown_agent")

    agent_id = canonical_agent_id(str(agent_row["agent_id"]))
    if agent_id not in MANUAL_RUNNERS:
        return ManualRunEligibility(False, "manual_runner_not_registered")
    if agent_row["status"] != "active":
        return ManualRunEligibility(False, "agent_not_active")
    if not bool(agent_row["enabled"]):
        return ManualRunEligibility(False, "agent_disabled")
    if agent_row["risk_tier"] not in LOW_RISK_MANUAL_TIERS:
        return ManualRunEligibility(False, "risk_tier_not_manual_runnable")

    metadata = agent_row.get("metadata") or {}
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("manual_run_enabled") is not True
    ):
        return ManualRunEligibility(False, "manual_run_not_enabled")

    return ManualRunEligibility(True, "manual_run_allowed")
