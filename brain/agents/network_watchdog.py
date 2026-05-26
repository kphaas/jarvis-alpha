"""Read-only Network Watchdog agent."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from brain.agents.events import AgentEvent, emit_agent_event
from brain.agents.runtime import AgentRuntime, AgentRuntimeConfig
from brain.db.rls import platform_admin_connection
from brain.skills.handlers import build_skill_runner
from brain.skills.policy_gate import SkillInvocation
from brain.skills.unifi import unifi_skill_handlers

NETWORK_WATCHDOG_AGENT_ID = "network_watchdog"
DEFAULT_NETWORK_INTERVAL_SECONDS = 30


async def maybe_run_network_watchdog(pool: asyncpg.Pool) -> bool:
    runtime = AgentRuntime(
        AgentRuntimeConfig(
            agent_id=NETWORK_WATCHDOG_AGENT_ID,
            trigger_type="scheduled",
            source="buddy",
        ),
        pool=pool,
    )
    state = await runtime.load_state()
    if state is None:
        return False
    interval = int(
        state.metadata.get("poll_interval_seconds", DEFAULT_NETWORK_INTERVAL_SECONDS)
    )
    if not await runtime.claim_due(interval_seconds=interval):
        return False

    async def _run(run_id: UUID) -> dict[str, Any]:
        return await collect_and_emit_network_events(pool, run_id, state.metadata)

    await runtime.run_once(_run)
    return True


async def run_network_watchdog_now(pool: asyncpg.Pool):
    runtime = AgentRuntime(
        AgentRuntimeConfig(
            agent_id=NETWORK_WATCHDOG_AGENT_ID,
            trigger_type="manual",
            source="http",
        ),
        pool=pool,
    )
    state = await runtime.load_state()
    previous_metadata = state.metadata if state else {}

    async def _run(run_id: UUID) -> dict[str, Any]:
        return await collect_and_emit_network_events(pool, run_id, previous_metadata)

    return await runtime.run_once(_run)


async def collect_and_emit_network_events(
    pool: asyncpg.Pool,
    run_id: UUID,
    previous_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runner = build_skill_runner(handlers=unifi_skill_handlers())
    async with platform_admin_connection(
        source="buddy",
        audit_actor=NETWORK_WATCHDOG_AGENT_ID,
        pool=pool,
    ) as conn:
        wan = await runner.run(
            conn,
            SkillInvocation(
                agent_id=NETWORK_WATCHDOG_AGENT_ID,
                skill_name="unifi.wan_status",
                estimated_cost_usd=Decimal("0"),
            ),
        )
        clients = await runner.run(
            conn,
            SkillInvocation(
                agent_id=NETWORK_WATCHDOG_AGENT_ID,
                skill_name="unifi.clients",
                estimated_cost_usd=Decimal("0"),
            ),
        )
        health = await runner.run(
            conn,
            SkillInvocation(
                agent_id=NETWORK_WATCHDOG_AGENT_ID,
                skill_name="unifi.health_check",
                estimated_cost_usd=Decimal("0"),
            ),
        )

    snapshot = {
        "wan": wan.output if wan.executed else {"error": wan.decision.reason},
        "clients": clients.output
        if clients.executed
        else {"error": clients.decision.reason},
        "health": health.output
        if health.executed
        else {"error": health.decision.reason},
    }
    events = network_events_from_snapshot(snapshot, previous_metadata or {})

    event_ids: list[str] = []
    for event in events:
        event_with_run = event.model_copy(update={"run_id": run_id})
        result = await emit_agent_event(event_with_run, pool=pool)
        event_ids.append(result.event_id)

    runtime = AgentRuntime(
        AgentRuntimeConfig(
            agent_id=NETWORK_WATCHDOG_AGENT_ID,
            trigger_type="scheduled",
            source="buddy",
        ),
        pool=pool,
    )
    await runtime.update_metadata(
        {
            "last_client_keys": client_keys(snapshot.get("clients")),
            "last_wan_status": snapshot.get("wan", {}).get("wan_status"),
            "last_health_status": snapshot.get("health", {}).get("status"),
        }
    )
    return {"snapshot": snapshot, "event_ids": event_ids}


def network_events_from_snapshot(
    snapshot: dict[str, Any],
    previous_metadata: dict[str, Any],
) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    wan = snapshot.get("wan") or {}
    health = snapshot.get("health") or {}
    clients = snapshot.get("clients") or {}

    if wan.get("error"):
        events.append(
            _event(
                "network.wan_error",
                "UniFi WAN read failed",
                str(wan["error"]),
                "warning",
                {"wan": wan},
            )
        )
    elif wan.get("wan_status") not in {None, "up", "ok"}:
        events.append(
            _event(
                "network.wan_degraded",
                "WAN degraded",
                f"WAN status is {wan.get('wan_status')}",
                "warning",
                {"wan": wan},
            )
        )

    if health.get("error"):
        events.append(
            _event(
                "network.health_error",
                "UniFi health read failed",
                str(health["error"]),
                "warning",
                {"health": health},
            )
        )
    elif health.get("status") in {"degraded", "critical"}:
        events.append(
            _event(
                "network.health_degraded",
                "Network health degraded",
                "; ".join(health.get("errors") or []) or "UniFi health degraded",
                "warning" if health.get("status") == "degraded" else "critical",
                {"health": health},
            )
        )

    previous_keys = set(previous_metadata.get("last_client_keys") or [])
    current_keys = set(client_keys(clients))
    new_keys = sorted(current_keys - previous_keys)
    if previous_keys and new_keys:
        events.append(
            _event(
                "network.new_client",
                "New network client detected",
                f"{len(new_keys)} new client(s) joined the home network.",
                "info",
                {
                    "new_client_keys": new_keys[:25],
                    "client_count": clients.get("client_count"),
                },
            )
        )

    return events


def client_keys(clients_payload: Any) -> list[str]:
    if not isinstance(clients_payload, dict):
        return []
    clients = clients_payload.get("clients") or []
    keys: list[str] = []
    for client in clients:
        if not isinstance(client, dict):
            continue
        key = (
            client.get("mac")
            or client.get("ip")
            or client.get("hostname")
            or client.get("name")
        )
        if key:
            keys.append(str(key))
    return sorted(set(keys))


def _event(
    event_type: str,
    title: str,
    message: str,
    severity: str,
    payload: dict[str, Any],
) -> AgentEvent:
    return AgentEvent(
        agent_id=NETWORK_WATCHDOG_AGENT_ID,
        event_type=event_type,
        title=title,
        message=message,
        severity=severity,
        channel_key="alpha_events",
        payload=payload,
    )
