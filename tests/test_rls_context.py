from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brain.db.rls import RLSContext, set_rls_context


class FakeConn:
    def __init__(self, in_transaction: bool = True):
        self.in_transaction = in_transaction
        self.executed = []

    def is_in_transaction(self):
        return self.in_transaction

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "SELECT 1"


def test_rls_context_from_request_maps_admin_role():
    request = SimpleNamespace(
        url=SimpleNamespace(path="/v1/dream/health"),
        state=SimpleNamespace(
            user_id="ken",
            user_sub="ken-sub",
            role="admin",
            max_rating="adult",
            workspace_id="workspace-1",
        ),
    )

    ctx = RLSContext.from_request(request)

    assert ctx.user_id == "ken"
    assert ctx.role == "platform_admin"
    assert ctx.max_rating == "adult"
    assert ctx.workspace_id == "workspace-1"
    assert ctx.source == "http"
    assert ctx.audit_actor == "ken-sub"


def test_rls_context_from_request_fails_closed_without_identity():
    request = SimpleNamespace(
        url=SimpleNamespace(path="/v1/dream/sessions"),
        state=SimpleNamespace(role="admin"),
    )

    with pytest.raises(HTTPException) as exc:
        RLSContext.from_request(request)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_set_rls_context_sets_all_transaction_gucs():
    conn = FakeConn()
    ctx = RLSContext.platform_admin(source="dream", audit_actor="ken")

    await set_rls_context(conn, ctx)

    assert len(conn.executed) == 1
    query, args = conn.executed[0]
    assert "set_config('rls.user_id'" in query
    assert "set_config('rls.audit_actor'" in query
    assert args == ("system", "platform_admin", "adult", "", "dream", "ken")


@pytest.mark.asyncio
async def test_set_rls_context_requires_transaction():
    conn = FakeConn(in_transaction=False)
    ctx = RLSContext.platform_admin(source="test", audit_actor="test")

    with pytest.raises(RuntimeError):
        await set_rls_context(conn, ctx)
