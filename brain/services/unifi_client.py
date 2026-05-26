"""Brain-side UniFi Gateway client.

Brain never talks to the UDM Pro directly. All UniFi reads cross the Gateway
adapter over Tailscale with the service token from secrets.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

from brain.config.node_addresses import GATEWAY_URL
from brain.config.secrets import get_secret

GATEWAY_UNIFI_TIMEOUT_SEC = 60


class UniFiGatewayError(RuntimeError):
    """Raised when the Brain cannot read UniFi data through Gateway."""


def _gateway_get_sync(path: str) -> dict[str, Any]:
    base = GATEWAY_URL.rstrip("/")
    url = f"{base}{path}"
    try:
        token = get_secret("GATEWAY_TOKEN")
    except KeyError as exc:
        raise UniFiGatewayError("gateway token is not configured") from exc

    try:
        proc = subprocess.run(
            ["curl", "-sk", "-H", f"x-jarvis-token: {token}", url],
            capture_output=True,
            text=True,
            timeout=GATEWAY_UNIFI_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise UniFiGatewayError("gateway request timed out") from exc
    except Exception as exc:
        raise UniFiGatewayError(str(exc)) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or f"curl exit {proc.returncode}"
        raise UniFiGatewayError(detail)

    raw = (proc.stdout or "").strip()
    if not raw:
        raise UniFiGatewayError("gateway returned an empty response")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UniFiGatewayError("gateway returned non-json response") from exc

    if not isinstance(data, dict):
        raise UniFiGatewayError("gateway returned unexpected payload")

    return data


async def gateway_get(path: str) -> dict[str, Any]:
    """Read a Gateway UniFi route without blocking the event loop."""

    return await asyncio.to_thread(_gateway_get_sync, path)


async def get_status() -> dict[str, Any]:
    return await gateway_get("/v1/unifi/status")


async def get_wan_status() -> dict[str, Any]:
    return await gateway_get("/v1/unifi/wan")


async def get_clients() -> dict[str, Any]:
    return await gateway_get("/v1/unifi/clients")


async def get_summary() -> dict[str, Any]:
    return await gateway_get("/v1/unifi/summary")


async def get_health_check() -> dict[str, Any]:
    return await gateway_get("/v1/unifi/health-check")
