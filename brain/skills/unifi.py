"""Read-only UniFi skills."""

from __future__ import annotations

from typing import Any

from brain.adapters.unifi import UniFiGatewayAdapter
from brain.skills.runner import SkillCall


class UniFiSkillError(RuntimeError):
    """Raised when a UniFi read skill cannot return a valid payload."""


async def wan_status(call: SkillCall) -> dict[str, Any]:
    adapter = _adapter_from_call(call)
    return (await adapter.wan_status()).model_dump(exclude_none=True)


async def clients(call: SkillCall) -> dict[str, Any]:
    adapter = _adapter_from_call(call)
    return (await adapter.clients()).model_dump(exclude_none=True)


async def health_check(call: SkillCall) -> dict[str, Any]:
    adapter = _adapter_from_call(call)
    return (await adapter.health_check()).model_dump(exclude_none=True)


def unifi_skill_handlers(
    adapter: UniFiGatewayAdapter | None = None,
) -> dict[str, Any]:
    if adapter is None:
        return {
            "unifi.wan_status": wan_status,
            "unifi.clients": clients,
            "unifi.health_check": health_check,
        }

    async def _wan_status(call: SkillCall) -> dict[str, Any]:
        return (await adapter.wan_status()).model_dump(exclude_none=True)

    async def _clients(call: SkillCall) -> dict[str, Any]:
        return (await adapter.clients()).model_dump(exclude_none=True)

    async def _health_check(call: SkillCall) -> dict[str, Any]:
        return (await adapter.health_check()).model_dump(exclude_none=True)

    return {
        "unifi.wan_status": _wan_status,
        "unifi.clients": _clients,
        "unifi.health_check": _health_check,
    }


def _adapter_from_call(call: SkillCall) -> UniFiGatewayAdapter:
    injected = call.payload.get("_adapter")
    if injected is not None:
        return injected
    return UniFiGatewayAdapter()
