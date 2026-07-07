from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "https://localhost:8283")

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

import brain.routes.homie as homie
from brain.middleware.approval_classes import ROUTE_CLASSIFICATION


def _request(
    *,
    user_id: str = "ken",
    profile_id: str = "ken",
    role: str = "admin",
    actor_type: str = "user",
    display_name: str = "Ken",
) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/home/homie/state",
            "headers": [],
            "state": {},
        }
    )
    request.state.user_id = user_id
    request.state.profile_id = profile_id
    request.state.role = role
    request.state.actor_type = actor_type
    request.state.display_name = display_name
    return request


def _client(*, role: str = "admin", actor_type: str = "user") -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def inject_state(request: Request, call_next):
        request.state.user_id = "ken"
        request.state.profile_id = "ken"
        request.state.role = role
        request.state.actor_type = actor_type
        request.state.display_name = "Ken"
        return await call_next(request)

    app.include_router(homie.router)
    return TestClient(app)


def _entity(
    entity_id: str,
    friendly_name: str,
    *,
    state: str = "off",
) -> dict[str, object]:
    return {
        "entity_id": entity_id,
        "friendly_name": friendly_name,
        "state": state,
        "attributes": {},
    }


def _snapshot(
    *entities: dict[str, object],
    context: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "snapshot": {str(entity["entity_id"]): entity for entity in entities}
    }
    if context is not None:
        payload["context"] = context
    return payload


def _executed(
    entity: dict[str, object],
    service: str,
    *,
    policy_summary: str = "Adults can directly control this device.",
    confirmed_state: dict[str, object] | None = None,
    plan_context: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = {
        "mode": "executed",
        "plan": {
            "entity_id": entity["entity_id"],
            "friendly_name": entity["friendly_name"],
            "governance": {"policy_summary": policy_summary},
        },
        "execution": {
            "entity_id": entity["entity_id"],
            "service": service,
        },
    }
    if plan_context is not None:
        payload["plan"]["context"] = plan_context
    if confirmed_state is not None:
        payload["confirmed_state"] = confirmed_state
        payload["execution"]["confirmed_state"] = confirmed_state
    return payload


def _proposal(
    entity: dict[str, object],
    approval_id: str,
    *,
    policy_summary: str = "This device stays approval-gated before execution.",
    plan_context: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "mode": "proposal",
        "plan": {
            "entity_id": entity["entity_id"],
            "friendly_name": entity["friendly_name"],
            "governance": {"policy_summary": policy_summary},
            **({"context": plan_context} if plan_context is not None else {}),
        },
        "approval": {
            "approval_id": approval_id,
            "status": "pending_approval",
        },
        "proposal": {
            "kind": "approval_handoff",
            "governance": {"policy_summary": policy_summary},
        },
    }


def test_trusted_actor_headers_map_alpha_session_to_homie_headers() -> None:
    assert homie._trusted_actor_headers(_request()) == {
        "X-Actor-Id": "ken",
        "X-Actor-Kind": "adult",
        "X-Profile-Id": "ken",
        "X-Display-Name": "Ken",
    }
    assert homie._trusted_actor_headers(_request(role="child", display_name="Ava")) == {
        "X-Actor-Id": "ken",
        "X-Actor-Kind": "child",
        "X-Profile-Id": "ken",
        "X-Display-Name": "Ava",
    }


def test_trusted_actor_headers_reject_non_user_sessions() -> None:
    with pytest.raises(HTTPException, match="homie_user_session_required"):
        homie._trusted_actor_headers(_request(actor_type="service"))


def test_request_homie_gateway_uses_bearer_and_actor_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        is_success = True

        def json(self) -> dict[str, object]:
            return {"status": "ok"}

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object] | None,
        ) -> FakeResponse:
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setenv("JARVIS_HOME_GATEWAY_BASE_URL", "http://home-gateway.local:8124")
    monkeypatch.setenv("JARVIS_HOME_GATEWAY_TOKEN", "gateway-secret")
    monkeypatch.setattr(homie.httpx, "AsyncClient", FakeAsyncClient)

    payload = asyncio.run(
        homie._request_homie_gateway(
            "POST",
            "/v1/home/homie/action",
            request=_request(role="child", display_name="Ava"),
            body={"entity_id": "light.kitchen", "service": "turn_on"},
        )
    )

    assert payload == {"status": "ok"}
    assert captured["method"] == "POST"
    assert captured["url"] == "http://home-gateway.local:8124/v1/home/homie/action"
    assert captured["headers"] == {
        "Authorization": "Bearer gateway-secret",
        "X-Actor-Id": "ken",
        "X-Actor-Kind": "child",
        "X-Profile-Id": "ken",
        "X-Display-Name": "Ava",
    }
    assert captured["json"] == {"entity_id": "light.kitchen", "service": "turn_on"}


def test_homie_routes_proxy_expected_gateway_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, path, body))
        return {"method": method, "path": path}

    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    assert client.get("/v1/home/homie/state").json()["path"] == "/v1/home/homie/state"
    assert (
        client.post(
            "/v1/home/homie/action",
            json={"entity_id": "light.kitchen", "service": "turn_on"},
        ).json()["path"]
        == "/v1/home/homie/action"
    )
    assert (
        client.post(
            "/v1/home/homie/approvals/abc/review",
            json={"decision": "approve"},
        ).json()["path"]
        == "/v1/home/homie/approvals/abc/review"
    )
    assert client.post("/v1/home/homie/approvals/abc/resume").json()["path"] == (
        "/v1/home/homie/approvals/abc/resume"
    )
    assert client.post("/v1/home/homie/approvals/abc/execute").json()["path"] == (
        "/v1/home/homie/approvals/abc/execute"
    )

    assert calls == [
        ("GET", "/v1/home/homie/state", None),
        (
            "POST",
            "/v1/home/homie/action",
            {"entity_id": "light.kitchen", "service": "turn_on"},
        ),
        ("POST", "/v1/home/homie/approvals/abc/review", {"decision": "approve"}),
        ("POST", "/v1/home/homie/approvals/abc/resume", None),
        ("POST", "/v1/home/homie/approvals/abc/execute", None),
    ]


def test_homie_events_stream_route_proxies_expected_gateway_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_stream(
        path: str,
        *,
        request: Request,
    ):
        calls.append(path)
        yield "event: state_changed\n"
        yield 'data: {"entity_id":"light.kitchen"}\n\n'

    monkeypatch.setattr(homie, "_stream_homie_gateway", fake_stream)
    client = _client()

    response = client.get("/v1/home/homie/events/stream")

    assert response.status_code == 200
    assert "event: state_changed" in response.text
    assert calls == ["/v1/home/homie/events/stream"]


def test_homie_intent_route_reads_device_status_from_live_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kitchen = _entity("light.kitchen", "Kitchen Lights")

    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert method == "GET"
        assert path == "/v1/home/homie/state"
        return _snapshot(kitchen)

    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    response = client.post(
        "/v1/home/homie/intent",
        json={"text": "Are the kitchen lights on?", "surface": "chat"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "read"
    assert response.json()["reply"] == "Kitchen Lights is currently off."


def test_homie_intent_route_delegates_direct_actions_to_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    bass = _entity("number.living_room_bass", "Living Room Bass", state="5")

    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, path, body))
        if method == "GET":
            return _snapshot(bass)
        return _executed(bass, "set_value")

    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    response = client.post(
        "/v1/home/homie/intent",
        json={"text": "Set living room bass to 8", "surface": "chat"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "executed"
    assert response.json()["plan"]["entity_id"] == "number.living_room_bass"
    assert response.json()["execution"]["entity_id"] == "number.living_room_bass"
    assert response.json()["reply"].startswith("Done. Living Room Bass")
    assert response.json()["intent"] == {
        "kind": "action",
        "entity_id": "number.living_room_bass",
        "service": "set_value",
        "service_data": {"value": 8},
    }
    assert calls == [
        ("GET", "/v1/home/homie/state", None),
        (
            "POST",
            "/v1/home/homie/action",
            {
                "entity_id": "number.living_room_bass",
                "service": "set_value",
                "service_data": {"value": 8},
            },
        ),
    ]


def test_homie_intent_route_delegates_select_actions_to_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    speech = _entity(
        "select.living_room_speech_enhancement",
        "Living Room Speech Enhancement",
        state="Off",
    )
    speech["attributes"] = {"options": ["Off", "Low", "Medium", "High"]}

    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, path, body))
        if method == "GET":
            return _snapshot(speech)
        return _executed(speech, "select_option")

    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    response = client.post(
        "/v1/home/homie/intent",
        json={
            "text": "Set living room speech enhancement to Medium",
            "surface": "chat",
        },
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "executed"
    assert response.json()["intent"] == {
        "kind": "action",
        "entity_id": "select.living_room_speech_enhancement",
        "service": "select_option",
        "service_data": {"option": "Medium"},
    }
    assert calls == [
        ("GET", "/v1/home/homie/state", None),
        (
            "POST",
            "/v1/home/homie/action",
            {
                "entity_id": "select.living_room_speech_enhancement",
                "service": "select_option",
                "service_data": {"option": "Medium"},
            },
        ),
    ]


def test_homie_intent_route_delegates_climate_mode_actions_to_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    thermostat = _entity("climate.downstairs", "Downstairs Thermostat", state="cool")
    thermostat["attributes"] = {"hvac_modes": ["off", "heat", "cool", "auto"]}

    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, path, body))
        if method == "GET":
            return _snapshot(thermostat)
        return _executed(thermostat, "set_hvac_mode")

    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    response = client.post(
        "/v1/home/homie/intent",
        json={"text": "Set downstairs thermostat to heat", "surface": "chat"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "executed"
    assert response.json()["intent"] == {
        "kind": "action",
        "entity_id": "climate.downstairs",
        "service": "set_hvac_mode",
        "service_data": {"hvac_mode": "heat"},
    }
    assert calls == [
        ("GET", "/v1/home/homie/state", None),
        (
            "POST",
            "/v1/home/homie/action",
            {
                "entity_id": "climate.downstairs",
                "service": "set_hvac_mode",
                "service_data": {"hvac_mode": "heat"},
            },
        ),
    ]


def test_homie_intent_route_surfaces_approval_handoffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coffee_maker = _entity("switch.coffee_maker", "Coffee Maker")

    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if method == "GET":
            return _snapshot(coffee_maker)
        return _proposal(coffee_maker, "abc-123")

    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    response = client.post(
        "/v1/home/homie/intent",
        json={"text": "Turn on the coffee maker", "surface": "chat"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "proposal"
    assert response.json()["proposal"]["kind"] == "approval_handoff"
    assert response.json()["approval"] == {
        "approval_id": "abc-123",
        "status": "pending_approval",
    }
    assert "abc-123" in response.json()["reply"]
    assert "approval-gated" in response.json()["reply"]


def test_homie_intent_route_uses_gateway_context_to_disambiguate_rooms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    ryleigh = _entity("switch.sound_machine_ryleigh", "Sound Machine")
    sloane = _entity("switch.sound_machine_sloane", "Sound Machine")
    context = {
        "switch.sound_machine_ryleigh": {
            "room": {
                "id": "ryleigh_room",
                "label": "Ryleigh Room",
                "aliases": ["ryleigh room", "ryleigh"],
            }
        },
        "switch.sound_machine_sloane": {
            "room": {
                "id": "sloane_room",
                "label": "Sloane Room",
                "aliases": ["sloane room", "sloane"],
            }
        },
    }

    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, path, body))
        if method == "GET":
            return _snapshot(ryleigh, sloane, context=context)
        return _executed(
            ryleigh,
            "turn_on",
            confirmed_state={
                "entity_id": "switch.sound_machine_ryleigh",
                "state": "on",
            },
        )

    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    response = client.post(
        "/v1/home/homie/intent",
        json={"text": "Turn on the sound machine in Ryleigh room", "surface": "chat"},
    )

    assert response.status_code == 200
    assert response.json()["intent"]["entity_id"] == "switch.sound_machine_ryleigh"
    assert calls[1][2] == {
        "entity_id": "switch.sound_machine_ryleigh",
        "service": "turn_on",
    }


def test_homie_voice_intent_route_reuses_voice_transcription_and_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    kitchen = _entity("light.kitchen", "Kitchen Lights")

    async def fake_read_voice_upload(file) -> tuple[bytes, str, str]:
        return (b"audio", "voice.webm", "audio/webm")

    async def fake_forward_voice_upload(
        *,
        request: Request,
        data: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, object]:
        assert data == b"audio"
        assert filename == "voice.webm"
        assert content_type == "audio/webm"
        return {"text": "turn on kitchen lights"}

    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, path, body))
        if method == "GET":
            return _snapshot(kitchen)
        return _executed(kitchen, "turn_on")

    monkeypatch.setattr(homie, "_read_voice_upload", fake_read_voice_upload)
    monkeypatch.setattr(homie, "_forward_voice_upload", fake_forward_voice_upload)
    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    response = client.post(
        "/v1/home/homie/voice-intent",
        files={"file": ("voice.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "executed"
    assert response.json()["surface"] == "voice"
    assert response.json()["transcript"] == "turn on kitchen lights"
    assert calls == [
        ("GET", "/v1/home/homie/state", None),
        (
            "POST",
            "/v1/home/homie/action",
            {"entity_id": "light.kitchen", "service": "turn_on"},
        ),
    ]


def test_homie_voice_intent_route_can_surface_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coffee_maker = _entity("switch.coffee_maker", "Coffee Maker")

    async def fake_read_voice_upload(file) -> tuple[bytes, str, str]:
        return (b"audio", "voice.webm", "audio/webm")

    async def fake_forward_voice_upload(
        *,
        request: Request,
        data: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, object]:
        return {"text": "turn on coffee maker"}

    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if method == "GET":
            return _snapshot(coffee_maker)
        return _proposal(coffee_maker, "approval-1")

    monkeypatch.setattr(homie, "_read_voice_upload", fake_read_voice_upload)
    monkeypatch.setattr(homie, "_forward_voice_upload", fake_forward_voice_upload)
    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    response = client.post(
        "/v1/home/homie/voice-intent",
        files={"file": ("voice.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "proposal"
    assert response.json()["transcript"] == "turn on coffee maker"
    assert response.json()["proposal"]["kind"] == "approval_handoff"
    assert response.json()["approval"] == {
        "approval_id": "approval-1",
        "status": "pending_approval",
    }
    assert "approval-1" in response.json()["reply"]


def test_homie_intent_route_returns_unresolved_for_unknown_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request(
        method: str,
        path: str,
        *,
        request: Request,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {"snapshot": {}}

    monkeypatch.setattr(homie, "_request_homie_gateway", fake_request)
    client = _client()

    response = client.post(
        "/v1/home/homie/intent",
        json={"text": "Turn on the moon lamp", "surface": "voice"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "unresolved"
    assert "could not match" in response.json()["reply"]


def test_home_homie_routes_are_classified() -> None:
    assert ROUTE_CLASSIFICATION["GET /v1/home/homie/state"] == ["read", "security_read"]
    assert ROUTE_CLASSIFICATION["GET /v1/home/homie/events/stream"] == [
        "read",
        "security_read",
    ]
    assert ROUTE_CLASSIFICATION["POST /v1/home/homie/intent"] == [
        "write",
        "security_write",
    ]
    assert ROUTE_CLASSIFICATION["POST /v1/home/homie/voice-intent"] == [
        "write",
        "security_write",
    ]
    assert ROUTE_CLASSIFICATION["POST /v1/home/homie/action"] == [
        "write",
        "security_write",
    ]
    assert ROUTE_CLASSIFICATION[
        "POST /v1/home/homie/approvals/{approval_id}/review"
    ] == [
        "write",
        "security_write",
    ]
    assert ROUTE_CLASSIFICATION[
        "POST /v1/home/homie/approvals/{approval_id}/resume"
    ] == [
        "write",
        "security_write",
    ]
    assert ROUTE_CLASSIFICATION[
        "POST /v1/home/homie/approvals/{approval_id}/execute"
    ] == [
        "write",
        "security_write",
    ]
