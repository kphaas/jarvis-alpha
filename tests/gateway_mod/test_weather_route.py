import pytest
from fastapi import HTTPException

from gateway.routes import weather
from gateway.routes.weather import current_weather


def _secret(name: str) -> str:
    values = {
        "GATEWAY_TOKEN": "gateway-token",
        "WEATHER_HOME_LATITUDE": "40.7128",
        "WEATHER_HOME_LONGITUDE": "-74.0060",
    }
    return values[name]


def _provider_payload() -> dict:
    return {
        "latitude": 40.71,
        "longitude": -74.01,
        "current": {
            "time": "2026-05-26T12:00",
            "temperature_2m": 72.4,
            "apparent_temperature": 73.1,
            "relative_humidity_2m": 51,
            "precipitation": 0,
            "weather_code": 1,
            "cloud_cover": 20,
            "wind_speed_10m": 4.8,
            "wind_gusts_10m": 9.2,
        },
    }


@pytest.mark.asyncio
async def test_current_weather_fetches_open_meteo_with_gateway_auth(monkeypatch):
    seen: dict[str, float] = {}

    def fake_fetch(latitude: float, longitude: float) -> dict:
        seen["latitude"] = latitude
        seen["longitude"] = longitude
        return _provider_payload()

    monkeypatch.setattr("gateway.routes.weather.get_secret", _secret)
    monkeypatch.setattr("gateway.routes.weather._fetch_open_meteo_sync", fake_fetch)
    weather._WEATHER_CACHE.clear()

    response = await current_weather(
        authorization="Bearer gateway-token",
        latitude=40.7128,
        longitude=-74.0060,
        location_label="home",
    )

    assert response.status == "ok"
    assert response.provider == "open-meteo"
    assert response.condition == "mostly clear"
    assert response.temperature_f == 72.4
    assert response.cached is False
    assert seen == {"latitude": 40.7128, "longitude": -74.006}


@pytest.mark.asyncio
async def test_current_weather_uses_configured_home_coordinates(monkeypatch):
    seen: dict[str, float] = {}

    def fake_fetch(latitude: float, longitude: float) -> dict:
        seen["latitude"] = latitude
        seen["longitude"] = longitude
        return _provider_payload()

    monkeypatch.setattr("gateway.routes.weather.get_secret", _secret)
    monkeypatch.setattr("gateway.routes.weather._fetch_open_meteo_sync", fake_fetch)
    weather._WEATHER_CACHE.clear()

    response = await current_weather(
        authorization="Bearer gateway-token",
        latitude=None,
        longitude=None,
        location_label="home",
    )

    assert response.status == "ok"
    assert seen == {"latitude": 40.7128, "longitude": -74.006}


@pytest.mark.asyncio
async def test_current_weather_rejects_bad_gateway_token(monkeypatch):
    monkeypatch.setattr("gateway.routes.weather.get_secret", _secret)

    with pytest.raises(HTTPException) as exc:
        await current_weather(
            authorization="Bearer wrong-token",
            latitude=None,
            longitude=None,
            location_label="home",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_current_weather_cache_is_reused(monkeypatch):
    calls = 0

    def fake_fetch(latitude: float, longitude: float) -> dict:
        nonlocal calls
        calls += 1
        return _provider_payload()

    monkeypatch.setattr("gateway.routes.weather.get_secret", _secret)
    monkeypatch.setattr("gateway.routes.weather._fetch_open_meteo_sync", fake_fetch)
    weather._WEATHER_CACHE.clear()

    first = await current_weather(
        authorization="Bearer gateway-token",
        latitude=40.7128,
        longitude=-74.0060,
        location_label="home",
    )
    second = await current_weather(
        authorization="Bearer gateway-token",
        latitude=40.7128,
        longitude=-74.0060,
        location_label="home",
    )

    assert first.cached is False
    assert second.cached is True
    assert calls == 1
