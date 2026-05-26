"""Brain-side weather Gateway client.

Brain does not call public weather APIs directly. Weather reads go through the
Gateway adapter over Tailscale with the Gateway service token.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any
from urllib.parse import urlencode

from brain.config.node_addresses import GATEWAY_URL
from brain.config.secrets import get_secret

GATEWAY_WEATHER_TIMEOUT_SEC = 15


class WeatherGatewayError(RuntimeError):
    """Raised when Brain cannot read weather data through Gateway."""


def _gateway_weather_current_sync(params: dict[str, Any]) -> dict[str, Any]:
    base = GATEWAY_URL.rstrip("/")
    query = urlencode(
        {key: value for key, value in params.items() if value is not None}
    )
    path = "/v1/weather/current"
    url = f"{base}{path}?{query}" if query else f"{base}{path}"
    try:
        token = get_secret("GATEWAY_TOKEN")
    except KeyError as exc:
        raise WeatherGatewayError("gateway token is not configured") from exc

    try:
        proc = subprocess.run(
            [
                "curl",
                "-sk",
                "-m",
                str(GATEWAY_WEATHER_TIMEOUT_SEC),
                "-H",
                f"Authorization: Bearer {token}",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=GATEWAY_WEATHER_TIMEOUT_SEC + 5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WeatherGatewayError("gateway weather request timed out") from exc
    except Exception as exc:
        raise WeatherGatewayError(str(exc)) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or f"curl exit {proc.returncode}"
        raise WeatherGatewayError(detail)

    raw = (proc.stdout or "").strip()
    if not raw:
        raise WeatherGatewayError("gateway returned an empty response")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WeatherGatewayError("gateway returned non-json response") from exc

    if not isinstance(data, dict):
        raise WeatherGatewayError("gateway returned unexpected payload")
    if data.get("status") != "ok":
        raise WeatherGatewayError("gateway returned weather error")
    return data


async def get_current_weather(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read current weather without blocking the event loop."""

    return await asyncio.to_thread(_gateway_weather_current_sync, dict(params or {}))
