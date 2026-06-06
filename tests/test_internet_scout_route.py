from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route
from brain.routes import internet_scout
from brain.services.internet_scout.evidence import build_source_reference
from brain.services.internet_scout.models import (
    InternetEvidencePacket,
    InternetScoutRequest,
)


def _request(*, scopes: list[str] | None = None, role: str = "user"):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_id="ken",
            role=role,
            actor_type="user",
            scopes=scopes or [],
        ),
        url=SimpleNamespace(path="/v1/internet-scout/research"),
    )


class FakeRepo:
    request_id = uuid4()
    created: list[object] = []
    events: list[dict[str, object]] = []
    stored: list[object] = []

    def __init__(self, conn) -> None:
        self.conn = conn

    async def create_request(self, **kwargs):
        self.created.append(kwargs)
        return self.request_id

    async def record_tool_event(self, **kwargs):
        self.events.append(kwargs)

    async def store_packet(self, **kwargs):
        self.stored.append(kwargs)

    async def mark_request_succeeded(self, request_id):
        self.events.append({"mark": "succeeded", "request_id": request_id})

    async def mark_request_failed(self, request_id, error_text):
        self.events.append(
            {"mark": "failed", "request_id": request_id, "error_text": error_text}
        )

    async def load_packet(self, request_id):
        source = build_source_reference(
            url="https://public.example.test/report",
            content="Stored",
        )
        return InternetEvidencePacket(
            request=InternetScoutRequest(requester="stored"),
            sources=[source],
            claims=[],
        )


class FakeExecutor:
    async def execute(self, body):
        source = build_source_reference(
            url="https://public.example.test/report",
            content="Beacon source.",
        )
        return None, InternetEvidencePacket(
            request=body,
            sources=[source],
            claims=[],
        )


@asynccontextmanager
async def fake_rls_connection(request):
    yield object()


@pytest.mark.asyncio
async def test_internet_scout_research_requires_scope():
    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_research(
            InternetScoutRequest(query="beacon"),
            _request(),
            _user_id="ken",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_internet_scout_research_stores_evidence(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(internet_scout, "InternetScoutExecutor", lambda: FakeExecutor())

    response = await internet_scout.internet_scout_research(
        InternetScoutRequest(query="beacon"),
        _request(scopes=["internet_scout.research"]),
        _user_id="ken",
    )

    assert response.request_id == FakeRepo.request_id
    assert response.evidence.sources[0].host == "public.example.test"
    assert FakeRepo.created[0]["user_id"] == "ken"
    assert any(event.get("status") == "succeeded" for event in FakeRepo.events)
    assert FakeRepo.stored


@pytest.mark.asyncio
async def test_internet_scout_loads_stored_evidence(monkeypatch):
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)

    response = await internet_scout.internet_scout_request(
        FakeRepo.request_id,
        _request(scopes=["internet_scout.read"]),
        _user_id="ken",
    )

    assert response.request_id == FakeRepo.request_id
    assert response.evidence.sources[0].url == "https://public.example.test/report"


def test_internet_scout_routes_are_classified():
    assert classify_route("POST", "/v1/internet-scout/research") == [
        "write",
        "external_call",
        "cost_incurring",
    ]
    assert classify_route("GET", "/v1/internet-scout/requests/123") == [
        "read",
        "security_read",
    ]
