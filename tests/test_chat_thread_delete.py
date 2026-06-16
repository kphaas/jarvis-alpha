from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8283")

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import chat


def _request(*, role: str = "admin", child_age: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            actor_type="user",
            role=role,
            user_id="ken" if role != "child" else "ryleigh",
            child_age=child_age,
        )
    )


def test_thread_delete_is_self_service_write_not_approval_gated() -> None:
    classes = classify_route(
        "DELETE", "/v1/threads/00000000-0000-0000-0000-000000000001"
    )

    assert classes == ["write"]
    assert determine_risk_tier(classes) == "T2"


def test_thread_cap_counts_pinned_and_recent_unarchived_threads() -> None:
    assert chat.MAX_PERSONAL_THREADS == 30
    assert chat.MAX_PROJECT_THREADS == 15
    assert chat.THREAD_CAP_RETENTION_DAYS == 30
    assert "pinned = TRUE" in chat.THREAD_CAP_ACTIVE_FILTER
    assert "updated_at >= now() - INTERVAL '30 days'" in chat.THREAD_CAP_ACTIVE_FILTER


@pytest.mark.asyncio
async def test_child_thread_delete_denied_before_db_touch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rls_connection(request: SimpleNamespace):
        raise AssertionError("child delete must fail before DB access")

    monkeypatch.setattr(chat, "rls_connection", rls_connection)

    with pytest.raises(HTTPException) as exc:
        await chat.archive_thread(str(uuid4()), _request(role="child", child_age=8))

    assert exc.value.status_code == 403
    assert exc.value.detail == "child_thread_delete_denied"


@pytest.mark.asyncio
async def test_adult_thread_delete_stays_scoped_to_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread_id = str(uuid4())
    calls: list[tuple[str, object, str]] = []

    class FakeConn:
        async def execute(self, query: str, thread_uuid: object, user_id: str) -> str:
            calls.append((query, thread_uuid, user_id))
            return "UPDATE 1"

    class FakeRlsConnection:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    def rls_connection(request: SimpleNamespace) -> FakeRlsConnection:
        return FakeRlsConnection()

    monkeypatch.setattr(chat, "rls_connection", rls_connection)

    response = await chat.archive_thread(thread_id, _request())

    assert response == {"ok": True}
    assert calls[0][2] == "ken"
    assert "WHERE id=$1 AND user_id=$2" in calls[0][0]


@pytest.mark.asyncio
async def test_thread_patch_can_pin_without_renaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread_id = str(uuid4())
    calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeConn:
        async def execute(self, query: str, *values: object) -> str:
            calls.append((query, values))
            return "UPDATE 1"

    class FakeRlsConnection:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    def rls_connection(request: SimpleNamespace) -> FakeRlsConnection:
        return FakeRlsConnection()

    monkeypatch.setattr(chat, "rls_connection", rls_connection)

    response = await chat.rename_thread(
        thread_id,
        chat.ThreadPatch(pinned=True),
        _request(),
    )

    assert response == {"ok": True}
    assert "pinned=$1" in calls[0][0]
    assert "WHERE id=$2 AND user_id=$3" in calls[0][0]
    assert calls[0][1][0] is True
    assert str(calls[0][1][1]) == thread_id
    assert calls[0][1][2] == "ken"
