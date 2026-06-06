from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import bcrypt
import pytest

from brain.routes import pin_auth
from brain.services import family_pin_sync
from brain.services.family_pin_sync import FamilyPinSyncError


def _request() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(iss="user"))


@pytest.mark.asyncio
async def test_set_admin_pin_succeeds_when_family_sync_degrades(monkeypatch) -> None:
    current_pin = "old-pin"
    new_pin = "new-pin"
    current_hash = bcrypt.hashpw(
        current_pin.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")
    calls = SimpleNamespace(updated_hash=None, connection_count=0)

    class FakeConn:
        async def fetchrow(self, query, *args):
            return {
                "id": "ken",
                "role": "admin",
                "pin_hash": current_hash,
            }

        async def execute(self, query, *args):
            calls.updated_hash = args[0]
            return "UPDATE 1"

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        calls.connection_count += 1
        yield FakeConn()

    async def fake_sync_family_pin_hash(profile_id: str, pin_hash: str) -> None:
        raise FamilyPinSyncError("family unavailable")

    monkeypatch.setattr(
        pin_auth,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )
    monkeypatch.setattr(
        pin_auth,
        "sync_family_pin_hash",
        fake_sync_family_pin_hash,
    )

    response = await pin_auth.set_admin_pin(
        _request(),
        pin_auth.SetAdminPinRequest(current_pin=current_pin, new_pin=new_pin),
    )

    assert response == {
        "status": "ok",
        "profile_id": "ken",
        "family_sync_status": "failed",
    }
    assert calls.connection_count == 2
    assert calls.updated_hash is not None
    assert bcrypt.checkpw(new_pin.encode("utf-8"), calls.updated_hash.encode("utf-8"))


@pytest.mark.asyncio
async def test_family_pin_sync_uses_stable_member_id_for_ken(monkeypatch) -> None:
    calls = SimpleNamespace(args=None, closed=False)

    class FakeConn:
        async def fetchrow(self, query, *args):
            calls.args = args
            assert "id = $3::uuid" in query
            assert "lower(name) = lower($4)" in query
            return {"id": args[2]}

        async def close(self):
            calls.closed = True

    async def fake_connect(dsn):
        assert dsn == "postgres://family"
        return FakeConn()

    monkeypatch.setenv("JARVIS_FAMILY_DB_DSN", "postgres://family")
    monkeypatch.setattr(family_pin_sync.asyncpg, "connect", fake_connect)

    await family_pin_sync.sync_family_pin_hash("ken", "hash")

    assert calls.args is not None
    assert str(calls.args[2]) == "abb3b4a8-8bfc-4a10-bdf6-c1c12993e493"
    assert calls.args[3] == "Ken"
    assert calls.closed is True
