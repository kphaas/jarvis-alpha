import pytest

from brain.config.secrets import clear_cache
from brain.services import weather_client


@pytest.fixture(autouse=True)
def clear_weather_secret_cache(monkeypatch):
    for name in (
        "WEATHER_HOME_LATITUDE",
        "WEATHER_HOME_LONGITUDE",
        "GATEWAY_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
        clear_cache(name)
    yield
    clear_cache()


@pytest.mark.asyncio
async def test_weather_client_sends_alpha_home_coordinates(monkeypatch):
    seen: dict = {}
    monkeypatch.setenv("WEATHER_HOME_LATITUDE", "34.028927")
    monkeypatch.setenv("WEATHER_HOME_LONGITUDE", "-84.198578")

    def fake_gateway_call(params: dict) -> dict:
        seen.update(params)
        return {"status": "ok"}

    monkeypatch.setattr(
        weather_client, "_gateway_weather_current_sync", fake_gateway_call
    )

    result = await weather_client.get_current_weather({"location_label": "home"})

    assert result == {"status": "ok"}
    assert seen == {
        "location_label": "home",
        "latitude": 34.028927,
        "longitude": -84.198578,
    }


@pytest.mark.asyncio
async def test_weather_client_preserves_explicit_coordinates(monkeypatch):
    seen: dict = {}
    monkeypatch.setenv("WEATHER_HOME_LATITUDE", "34.028927")
    monkeypatch.setenv("WEATHER_HOME_LONGITUDE", "-84.198578")

    def fake_gateway_call(params: dict) -> dict:
        seen.update(params)
        return {"status": "ok"}

    monkeypatch.setattr(
        weather_client, "_gateway_weather_current_sync", fake_gateway_call
    )

    await weather_client.get_current_weather(
        {
            "location_label": "custom",
            "latitude": 40.7128,
            "longitude": -74.006,
        }
    )

    assert seen == {
        "location_label": "custom",
        "latitude": 40.7128,
        "longitude": -74.006,
    }
