"""Read-only Sweep network security agent."""

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

SWEEP_AGENT_ID = "sweep"
NETWORK_WATCHDOG_AGENT_ID = SWEEP_AGENT_ID
NETWORK_WATCHDOG_AGENT_ALIAS = "network_watchdog"
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
    snapshot["unknown_device_quarantine"] = quarantine_recommendation(
        snapshot.get("clients"),
        previous_metadata or {},
    )
    snapshot["firmware_drift"] = firmware_drift(snapshot.get("health"))
    snapshot["wan_failover_health"] = wan_failover_health(snapshot.get("wan"))
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
            "last_health_signature": health_signature(snapshot.get("health")),
            "last_tls_public_key_pin_configured": tls_public_key_pin_configured(
                snapshot.get("health")
            ),
            "last_firmware_drift_signature": firmware_drift_signature(
                snapshot.get("firmware_drift")
            ),
            "last_wan_failover_status": snapshot.get("wan_failover_health", {}).get(
                "status"
            ),
            "last_unknown_device_keys": snapshot.get(
                "unknown_device_quarantine", {}
            ).get("unknown_client_keys", []),
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

    current_wan_status = wan.get("wan_status")
    previous_wan_status = previous_metadata.get("last_wan_status")
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
    elif (
        current_wan_status not in {None, "up", "ok"}
        and current_wan_status != previous_wan_status
    ):
        events.append(
            _event(
                "network.wan_degraded",
                "WAN degraded",
                f"WAN status is {current_wan_status}",
                "warning",
                {"wan": wan},
            )
        )

    current_health_signature = health_signature(health)
    previous_health_signature = previous_metadata.get("last_health_signature")
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
    elif (
        health.get("status") in {"degraded", "critical"}
        and current_health_signature != previous_health_signature
    ):
        events.append(
            _event(
                "network.health_degraded",
                "Network health degraded",
                "; ".join(health.get("errors") or []) or "UniFi health degraded",
                "warning" if health.get("status") == "degraded" else "critical",
                {"health": health},
            )
        )

    tls = health.get("tls") or {}
    current_tls_pin = tls_public_key_pin_configured(health)
    previous_tls_pin = previous_metadata.get("last_tls_public_key_pin_configured")
    if current_tls_pin is False and previous_tls_pin is not False:
        events.append(
            _event(
                "network.unifi_tls_unpinned",
                "UniFi TLS pin missing",
                "Sweep detected UniFi TLS is verified without the expected public-key pin.",
                "warning",
                {"tls": tls},
            )
        )

    previous_keys = set(previous_metadata.get("last_client_keys") or [])
    current_keys = set(client_keys(clients))
    new_keys = sorted(current_keys - previous_keys)
    if previous_keys and new_keys:
        quarantine = quarantine_recommendation(clients, previous_metadata)
        events.append(
            _event(
                "network.new_client",
                "New network client detected",
                f"{len(new_keys)} new client(s) joined the home network.",
                "info",
                {
                    "new_client_keys": new_keys[:25],
                    "client_count": clients.get("client_count"),
                    "quarantine_recommendation": quarantine,
                },
            )
        )

    drift = snapshot.get("firmware_drift")
    drift_signature = firmware_drift_signature(drift)
    if (
        isinstance(drift, dict)
        and drift.get("status") == "warn"
        and drift_signature != previous_metadata.get("last_firmware_drift_signature")
    ):
        events.append(
            _event(
                "network.firmware_drift",
                "UniFi firmware drift detected",
                drift.get("summary")
                or "One or more UniFi devices have updates available.",
                "warning",
                {"firmware_drift": drift},
            )
        )

    failover = snapshot.get("wan_failover_health")
    failover_status = failover.get("status") if isinstance(failover, dict) else None
    if failover_status in {"warn", "fail"} and failover_status != previous_metadata.get(
        "last_wan_failover_status"
    ):
        events.append(
            _event(
                "network.wan_failover_health",
                "WAN failover needs review",
                failover.get("summary") or "WAN failover health needs review.",
                "warning" if failover_status == "warn" else "critical",
                {"wan_failover_health": failover},
            )
        )

    return events


def health_signature(health_payload: Any) -> str | None:
    if not isinstance(health_payload, dict):
        return None
    status = str(health_payload.get("status") or "unknown")
    errors = health_payload.get("errors") or []
    if not isinstance(errors, list):
        errors = [str(errors)]
    return "|".join([status, *sorted(str(error) for error in errors)])


def tls_public_key_pin_configured(health_payload: Any) -> bool | None:
    if not isinstance(health_payload, dict):
        return None
    tls = health_payload.get("tls")
    if not isinstance(tls, dict):
        return None
    value = tls.get("public_key_pin_configured")
    return value if isinstance(value, bool) else None


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


def quarantine_recommendation(
    clients_payload: Any,
    previous_metadata: dict[str, Any],
) -> dict[str, Any]:
    previous_keys = set(previous_metadata.get("last_client_keys") or [])
    current_keys = set(client_keys(clients_payload))
    unknown_keys = sorted(current_keys - previous_keys)
    if not previous_keys:
        return {
            "status": "baseline_required",
            "summary": "Sweep needs one baseline run before it can recommend quarantine.",
            "unknown_count": 0,
            "unknown_client_keys": [],
            "action": "baseline_only",
            "mutates_network": False,
        }
    return {
        "status": "review" if unknown_keys else "pass",
        "summary": (
            f"Review {len(unknown_keys)} unknown client(s) before quarantine."
            if unknown_keys
            else "No unknown clients detected against the last Sweep baseline."
        ),
        "unknown_count": len(unknown_keys),
        "unknown_client_keys": unknown_keys[:25],
        "action": "recommend_quarantine_if_unknown" if unknown_keys else "none",
        "mutates_network": False,
    }


def firmware_drift(health_payload: Any) -> dict[str, Any]:
    if not isinstance(health_payload, dict) or health_payload.get("error"):
        return {
            "status": "unavailable",
            "summary": "UniFi firmware inventory is unavailable.",
            "devices": [],
        }
    drifting = []
    for device in health_payload.get("devices") or []:
        if not isinstance(device, dict):
            continue
        upgradeable = bool(
            device.get("upgradeable")
            or device.get("upgradable")
            or device.get("has_upgrade")
            or device.get("upgrade_available")
        )
        target = (
            device.get("target_version")
            or device.get("upgrade_to_firmware")
            or device.get("upgrade_to_version")
            or device.get("latest_version")
            or device.get("version_latest")
        )
        if not upgradeable and not target:
            continue
        drifting.append(
            {
                "name": device.get("name") or device.get("mac") or "unknown",
                "kind": device.get("kind") or "device",
                "model": device.get("model"),
                "version": device.get("version"),
                "target_version": target,
            }
        )
    return {
        "status": "warn" if drifting else "pass",
        "summary": (
            f"{len(drifting)} UniFi device(s) have firmware updates available."
            if drifting
            else "No UniFi firmware drift detected."
        ),
        "devices": drifting,
    }


def firmware_drift_signature(drift_payload: Any) -> str | None:
    if not isinstance(drift_payload, dict):
        return None
    devices = drift_payload.get("devices") or []
    if not isinstance(devices, list):
        return None
    parts = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        parts.append(
            "|".join(
                str(device.get(key) or "")
                for key in ("name", "kind", "version", "target_version")
            )
        )
    return ";".join(sorted(parts))


def wan_failover_health(wan_payload: Any) -> dict[str, Any]:
    if not isinstance(wan_payload, dict) or wan_payload.get("error"):
        return {
            "status": "unavailable",
            "summary": "UniFi WAN failover health is unavailable.",
        }
    wan_status = str(wan_payload.get("wan_status") or "unknown")
    if wan_status not in {"up", "ok"}:
        return {
            "status": "fail",
            "summary": f"Primary WAN is {wan_status}; failover readiness needs review.",
            "primary_wan_status": wan_status,
        }
    failover_ready = wan_payload.get("failover_ready")
    secondary_status = (
        wan_payload.get("secondary_wan_status")
        or wan_payload.get("wan2_status")
        or wan_payload.get("failover_status")
    )
    if failover_ready is True or str(secondary_status).lower() in {
        "up",
        "ok",
        "ready",
        "active",
        "standby",
    }:
        return {
            "status": "pass",
            "summary": "WAN failover appears ready from UniFi telemetry.",
            "primary_wan_status": wan_status,
            "secondary_wan_status": secondary_status,
        }
    return {
        "status": "warn",
        "summary": "UniFi did not report a ready secondary WAN/failover path.",
        "primary_wan_status": wan_status,
        "secondary_wan_status": secondary_status,
    }


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
