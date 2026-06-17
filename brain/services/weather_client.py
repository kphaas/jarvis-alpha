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
WEATHER_HOME_LATITUDE_SECRET = "WEATHER_HOME_LATITUDE"
WEATHER_HOME_LONGITUDE_SECRET = "WEATHER_HOME_LONGITUDE"


class WeatherGatewayError(RuntimeError):
    """Raised when Brain cannot read weather data through Gateway."""


def _gateway_weather_current_sync(params: dict[str, Any]) -> dict[str, Any]:
    params = _with_alpha_home_coordinates(params)
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
                "-sS",
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

    resolved_params = _with_alpha_home_coordinates(dict(params or {}))
    return await asyncio.to_thread(_gateway_weather_current_sync, resolved_params)


def _with_alpha_home_coordinates(params: dict[str, Any]) -> dict[str, Any]:
    """Send Alpha-owned home coordinates to Gateway when caller omits coords."""
    if params.get("latitude") is not None or params.get("longitude") is not None:
        return params

    latitude = _secret_or_none(WEATHER_HOME_LATITUDE_SECRET)
    longitude = _secret_or_none(WEATHER_HOME_LONGITUDE_SECRET)
    if latitude is None or longitude is None:
        return params

    try:
        resolved = {
            **params,
            "latitude": float(latitude),
            "longitude": float(longitude),
        }
    except ValueError as exc:
        raise WeatherGatewayError(
            "alpha weather home coordinates are not valid floats"
        ) from exc
    return resolved


def _secret_or_none(name: str) -> str | None:
    try:
        value = get_secret(name).strip()
    except KeyError:
        return None
    return value or None
