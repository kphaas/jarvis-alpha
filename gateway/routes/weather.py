"""Gateway weather adapter.

Gateway is Alpha's only public-internet egress. Brain and agents call this route
with the service token; Gateway calls Open-Meteo and returns a compact, cached
current-conditions payload.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_gateway")

router = APIRouter(prefix="/v1/weather", tags=["weather"])

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TIMEOUT_SEC = 10
WEATHER_CACHE_TTL_SEC = int(os.getenv("JARVIS_WEATHER_CACHE_TTL_SEC", "600"))

_WEATHER_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class CurrentWeatherResponse(BaseModel):
    status: Literal["ok"]
    provider: Literal["open-meteo"] = "open-meteo"
    location_label: str
    observed_at: str | None = None
    latitude: float
    longitude: float
    temperature_f: float | None = None
    apparent_temperature_f: float | None = None
    relative_humidity_pct: int | None = None
    precipitation_in: float | None = None
    weather_code: int | None = None
    condition: str
    cloud_cover_pct: int | None = None
    wind_speed_mph: float | None = None
    wind_gust_mph: float | None = None
    cached: bool = False


def _authorize_gateway_call(authorization: str) -> None:
    expected = get_secret("GATEWAY_TOKEN")
    if not authorization.startswith("Bearer ") or authorization[7:] != expected:
        raise HTTPException(status_code=403, detail="Invalid gateway token")


def _configured_coordinate(name: str) -> float:
    try:
        return float(get_secret(name))
    except KeyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{name} is not configured on Gateway",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{name} is not a valid coordinate",
        ) from exc


def _coordinates(
    latitude: float | None, longitude: float | None
) -> tuple[float, float]:
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=422,
            detail="latitude and longitude must be provided together",
        )
    lat = (
        latitude
        if latitude is not None
        else _configured_coordinate("WEATHER_HOME_LATITUDE")
    )
    lon = (
        longitude
        if longitude is not None
        else _configured_coordinate("WEATHER_HOME_LONGITUDE")
    )
    if not -90 <= lat <= 90:
        raise HTTPException(status_code=422, detail="latitude is out of range")
    if not -180 <= lon <= 180:
        raise HTTPException(status_code=422, detail="longitude is out of range")
    return lat, lon


def _cache_key(latitude: float, longitude: float) -> str:
    return f"{latitude:.4f}:{longitude:.4f}:fahrenheit:mph"


def _condition(weather_code: int | None) -> str:
    return {
        0: "clear",
        1: "mostly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "fog",
        48: "freezing fog",
        51: "light drizzle",
        53: "drizzle",
        55: "heavy drizzle",
        56: "light freezing drizzle",
        57: "freezing drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        66: "light freezing rain",
        67: "freezing rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        77: "snow grains",
        80: "light showers",
        81: "showers",
        82: "heavy showers",
        85: "light snow showers",
        86: "snow showers",
        95: "thunderstorm",
        96: "thunderstorm with hail",
        99: "severe thunderstorm with hail",
    }.get(weather_code, "unknown")


def _open_meteo_url(latitude: float, longitude: float) -> str:
    params = {
        "latitude": f"{latitude:.6f}",
        "longitude": f"{longitude:.6f}",
        "current": (
            "temperature_2m,apparent_temperature,relative_humidity_2m,"
            "precipitation,weather_code,cloud_cover,wind_speed_10m,wind_gusts_10m"
        ),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "auto",
        "forecast_days": "1",
    }
    return f"{OPEN_METEO_FORECAST_URL}?{urlencode(params)}"


def _fetch_open_meteo_sync(latitude: float, longitude: float) -> dict[str, Any]:
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-m",
            str(OPEN_METEO_TIMEOUT_SEC),
            _open_meteo_url(latitude, longitude),
        ],
        capture_output=True,
        text=True,
        timeout=OPEN_METEO_TIMEOUT_SEC + 5,
        check=False,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=502, detail="Weather provider transport failed")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail="Weather provider returned non-JSON"
        ) from exc

    if not isinstance(payload, dict) or "current" not in payload:
        raise HTTPException(
            status_code=502, detail="Weather provider response was incomplete"
        )
    return payload


def _response_payload(
    *,
    provider_payload: dict[str, Any],
    location_label: str,
    cached: bool,
) -> dict[str, Any]:
    current = provider_payload.get("current") or {}
    weather_code = current.get("weather_code")
    if weather_code is not None:
        weather_code = int(weather_code)

    return {
        "status": "ok",
        "provider": "open-meteo",
        "location_label": location_label,
        "observed_at": current.get("time"),
        "latitude": round(float(provider_payload["latitude"]), 4),
        "longitude": round(float(provider_payload["longitude"]), 4),
        "temperature_f": current.get("temperature_2m"),
        "apparent_temperature_f": current.get("apparent_temperature"),
        "relative_humidity_pct": current.get("relative_humidity_2m"),
        "precipitation_in": current.get("precipitation"),
        "weather_code": weather_code,
        "condition": _condition(weather_code),
        "cloud_cover_pct": current.get("cloud_cover"),
        "wind_speed_mph": current.get("wind_speed_10m"),
        "wind_gust_mph": current.get("wind_gusts_10m"),
        "cached": cached,
    }


@router.get("/current", response_model=CurrentWeatherResponse)
async def current_weather(
    authorization: str = Header(...),
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    location_label: str = Query(default="home", min_length=1, max_length=64),
) -> CurrentWeatherResponse:
    _authorize_gateway_call(authorization)
    lat, lon = _coordinates(latitude, longitude)
    cache_key = _cache_key(lat, lon)
    now = time.monotonic()
    cached = _WEATHER_CACHE.get(cache_key)
    if cached and now - cached[0] <= WEATHER_CACHE_TTL_SEC:
        payload = dict(cached[1])
        payload["location_label"] = location_label
        payload["cached"] = True
        return CurrentWeatherResponse.model_validate(payload)

    provider_payload = await asyncio.to_thread(_fetch_open_meteo_sync, lat, lon)
    payload = _response_payload(
        provider_payload=provider_payload,
        location_label=location_label,
        cached=False,
    )
    _WEATHER_CACHE[cache_key] = (now, payload)
    logger.info("weather_current fetched provider=open-meteo cached=false")
    return CurrentWeatherResponse.model_validate(payload)
