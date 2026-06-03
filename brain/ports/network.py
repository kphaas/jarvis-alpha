"""Network domain port contracts."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class WanStatus(BaseModel):
    reachable: bool = True
    wan_status: str = "unknown"
    wan_up_mbps: float | None = None
    wan_down_mbps: float | None = None
    latency_ms: float | None = None
    uptime_sec: int | None = None
    speedtest_status: str | None = None
    isp_name: str | None = None
    gw_name: str | None = None
    gw_cpu_pct: float | None = None
    gw_mem_pct: float | None = None
    error: str | None = None


class NetworkClient(BaseModel):
    mac: str | None = None
    ip: str | None = None
    hostname: str | None = None
    name: str | None = None
    is_wired: bool = False
    network: str | None = None
    essid: str | None = None
    last_seen: int | None = None
    vendor: str | None = None

    @property
    def stable_key(self) -> str:
        return self.mac or self.ip or self.hostname or self.name or "unknown"


class NetworkClients(BaseModel):
    reachable: bool = True
    client_count: int = 0
    wired_count: int = 0
    wireless_count: int = 0
    clients: list[NetworkClient] = Field(default_factory=list)
    error: str | None = None


class NetworkHealth(BaseModel):
    reachable: bool = True
    status: str = "unknown"
    wan_status: str = "unknown"
    client_count: int | None = None
    wired_count: int | None = None
    wireless_count: int | None = None
    ap_count: int = 0
    switch_count: int = 0
    gateway_count: int = 0
    offline_device_count: int = 0
    gw_cpu_pct: float | None = None
    gw_mem_pct: float | None = None
    tls: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    devices: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class NetworkPort(Protocol):
    async def wan_status(self) -> WanStatus:
        """Return WAN status from the home network."""

    async def clients(self) -> NetworkClients:
        """Return connected UniFi clients."""

    async def health_check(self) -> NetworkHealth:
        """Return controller, gateway, switch, and AP health."""
