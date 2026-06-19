from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import memory_consolidation


def test_memory_consolidation_proposal_route_passes_to_review_queue_bridge() -> None:
    classes = classify_route("POST", "/v1/memory/consolidation/proposals")

    assert classes == ["write"]
    assert "security_write" not in classes
    assert determine_risk_tier(classes) == "T2"


def test_memory_consolidation_execute_route_passes_to_proposal_bound_token() -> None:
    classes = classify_route(
        "POST",
        "/v1/memory/consolidation/proposals/11111111-1111-4111-8111-111111111111/execute",
    )

    assert classes == ["write"]
    assert "security_write" not in classes
    assert determine_risk_tier(classes) == "T2"


def test_memory_consolidation_archive_route_is_authenticated_write() -> None:
    classes = classify_route(
        "POST",
        "/v1/memory/consolidation/proposals/11111111-1111-4111-8111-111111111111/archive",
    )

    assert classes == ["write"]
    assert "security_write" not in classes
    assert determine_risk_tier(classes) == "T2"


def test_memory_consolidation_revert_route_is_t5_not_security_write() -> None:
    classes = classify_route(
        "POST",
        "/v1/memory/consolidation/proposals/11111111-1111-4111-8111-111111111111/revert",
    )

    assert classes == ["memory_consolidation_reviewed_write"]
    assert "security_write" not in classes
    assert determine_risk_tier(classes) == "T5"


def test_unknown_memory_consolidation_action_fails_closed() -> None:
    classes = classify_route("POST", "/v1/memory/consolidation/unknown-action")

    assert classes == ["unclassified"]
    assert determine_risk_tier(classes) == "T5"


class FakeArchiveConn:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object) -> dict:
        return {
            "id": UUID("11111111-1111-4111-8111-111111111111"),
            "executable": True,
            "status": "queued",
            "approval_queue_id": UUID("22222222-2222-4222-8222-222222222222"),
            "approval_status": "pending",
        }

    async def fetch(self, query: str, *args: object) -> list[dict]:
        self.fetch_calls.append((query, args))
        return []

    async def execute(self, query: str, *args: object) -> str:
        self.execute_calls.append((query, args))
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_memory_consolidation_archive_denies_pending_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeArchiveConn()

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source: str, audit_actor: str):
        assert source == "http"
        assert audit_actor == "ken"
        yield conn

    monkeypatch.setattr(
        memory_consolidation,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(user_id="ken", user_sub="ken", scopes=["memory.write"])
    )

    response = await memory_consolidation.archive_memory_consolidation_proposal(
        proposal_id=UUID("11111111-1111-4111-8111-111111111111"),
        request=request,
    )

    assert response.status == "archived"
    assert response.result["proposal_status"] == "rejected"
    assert response.result["approval_status"] == "denied"
    assert any("decide_approval" in call[0] for call in conn.fetch_calls)
    assert any("status = 'rejected'" in call[0] for call in conn.execute_calls)
