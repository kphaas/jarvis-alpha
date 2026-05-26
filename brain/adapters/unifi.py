"""UniFi adapter backed by the Alpha Gateway."""

from __future__ import annotations

from brain.ports.network import NetworkClients, NetworkHealth, WanStatus
from brain.services import unifi_client


class UniFiGatewayAdapter:
    """Read-only UniFi adapter.

    This adapter deliberately calls the Alpha Gateway rather than UDM Pro. That
    preserves the architecture boundary: Brain orchestrates, Gateway adapts.
    """

    async def wan_status(self) -> WanStatus:
        return WanStatus.model_validate(await unifi_client.get_wan_status())

    async def clients(self) -> NetworkClients:
        return NetworkClients.model_validate(await unifi_client.get_clients())

    async def health_check(self) -> NetworkHealth:
        return NetworkHealth.model_validate(await unifi_client.get_health_check())
