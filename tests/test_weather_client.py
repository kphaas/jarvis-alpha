import pytest

from brain.services import weather_client


@pytest.mark.asyncio
async def test_weather_client_sends_alpha_home_coordinates(monkeypatch):
    seen: dict = {}

    async def fake_home_coordinates():
        return 12.3456, -65.4321

    def fake_gateway_call(params: dict) -> dict:
        seen.update(params)
        return {"status": "ok"}

    monkeypatch.setattr(
        weather_client,
        "get_home_weather_coordinates",
        fake_home_coordinates,
    )
    monkeypatch.setattr(
        weather_client, "_gateway_weather_current_sync", fake_gateway_call
    )

    result = await weather_client.get_current_weather({"location_label": "home"})

    assert result == {"status": "ok"}
    assert seen == {
        "location_label": "home",
        "latitude": 12.3456,
        "longitude": -65.4321,
    }


@pytest.mark.asyncio
async def test_weather_client_preserves_explicit_coordinates(monkeypatch):
    seen: dict = {}
    home_coordinate_calls = 0

    async def fake_home_coordinates():
        nonlocal home_coordinate_calls
        home_coordinate_calls += 1
        return 12.3456, -65.4321

    def fake_gateway_call(params: dict) -> dict:
        seen.update(params)
        return {"status": "ok"}

    monkeypatch.setattr(
        weather_client,
        "get_home_weather_coordinates",
        fake_home_coordinates,
    )
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

    assert home_coordinate_calls == 0
    assert seen == {
        "location_label": "custom",
        "latitude": 40.7128,
        "longitude": -74.006,
    }
