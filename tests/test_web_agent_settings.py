from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route
from brain.routes import settings
from brain.services import weather_client
from brain.services.web_agent_settings import (
    HomeLocationUpdate,
    fetch_web_agent_settings,
    get_home_weather_coordinates,
    save_home_location,
)


class FakeRow(dict):
    def __getitem__(self, key):
        return self.get(key)


class FakeConn:
    def __init__(self, row=None):
        self.row = row
        self.saved_payload = None
        self.saved_profile = None

    async def fetchrow(self, _query, *args):
        if len(args) >= 3:
            self.saved_payload = json.loads(args[1])
            self.saved_profile = args[2]
            return FakeRow(
                home_location=self.saved_payload,
                updated_at=datetime(2026, 6, 18, tzinfo=UTC),
                updated_by_profile_id=self.saved_profile,
            )
        return self.row


def _request(*, role="admin", scopes=None):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_id="ken",
            profile_id="ken",
            role=role,
            actor_type="user",
            scopes=scopes if scopes is not None else ["*"],
        )
    )


def test_settings_routes_are_classified():
    assert classify_route("GET", "/v1/settings/web-agent") == [
        "read",
        "security_read",
    ]
    assert classify_route("PUT", "/v1/settings/web-agent/home-location") == [
        "write",
        "security_write",
    ]


@pytest.mark.asyncio
async def test_web_agent_settings_round_trip_home_location():
    conn = FakeConn()
    response = await save_home_location(
        conn,
        HomeLocationUpdate(
            label="Home",
            postal_code="12345",
            city="Testville",
            region="TS",
            country="us",
            latitude=12.3456,
            longitude=-65.4321,
        ),
        updated_by_profile_id="ken",
    )

    assert conn.saved_payload == {
        "label": "Home",
        "postal_code": "12345",
        "city": "Testville",
        "region": "TS",
        "country": "US",
        "latitude": 12.3456,
        "longitude": -65.4321,
    }
    assert conn.saved_profile == "ken"
    assert response.home_location is not None
    assert response.home_location.data_classification == "personal_information"
    assert response.home_location.updated_by_profile_id == "ken"


@pytest.mark.asyncio
async def test_web_agent_settings_empty_row_returns_no_home_location():
    response = await fetch_web_agent_settings(
        FakeConn(FakeRow(home_location={}, updated_at=None, updated_by_profile_id=None))
    )

    assert response.home_location is None
    assert response.storage_classification == "alpha_db_personal_settings"


@pytest.mark.asyncio
async def test_web_agent_settings_route_requires_admin():
    with pytest.raises(HTTPException) as exc:
        await settings.get_web_agent_settings(
            _request(role="child", scopes=["weather.read"]),
            _user_id="ryleigh",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_web_agent_settings_route_uses_platform_admin_context(monkeypatch):
    seen = {}
    conn = FakeConn(
        FakeRow(
            home_location={
                "label": "Home",
                "latitude": 12.3456,
                "longitude": -65.4321,
            },
            updated_at=datetime(2026, 6, 18, tzinfo=UTC),
            updated_by_profile_id="ken",
        )
    )

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        seen["source"] = source
        seen["audit_actor"] = audit_actor
        yield conn

    monkeypatch.setattr(
        settings,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )

    response = await settings.get_web_agent_settings(_request(), _user_id="ken")

    assert response.home_location is not None
    assert response.home_location.latitude == 12.3456
    assert seen == {
        "source": "http",
        "audit_actor": "settings_web_agent_read:ken",
    }


@pytest.mark.asyncio
async def test_home_weather_coordinates_read_from_db_settings(monkeypatch):
    conn = FakeConn(
        FakeRow(
            home_location={
                "label": "Home",
                "latitude": 12.3456,
                "longitude": -65.4321,
            },
            updated_at=datetime(2026, 6, 18, tzinfo=UTC),
            updated_by_profile_id="ken",
        )
    )

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        yield conn

    monkeypatch.setattr(
        "brain.services.web_agent_settings.platform_admin_connection",
        fake_platform_admin_connection,
    )

    assert await get_home_weather_coordinates() == (12.3456, -65.4321)


@pytest.mark.asyncio
async def test_weather_client_sends_db_home_coordinates(monkeypatch):
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
        weather_client,
        "_gateway_weather_current_sync",
        fake_gateway_call,
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
        weather_client,
        "_gateway_weather_current_sync",
        fake_gateway_call,
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
