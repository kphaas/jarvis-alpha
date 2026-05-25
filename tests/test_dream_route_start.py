"""Tests for Dream session Temporal start wiring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from temporalio.exceptions import WorkflowAlreadyStartedError

from brain.dream.client import DreamWorkflowStart
from brain.routes import dream as dream_route


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self, session=None):
        self.session = session
        self.executed = []

    def transaction(self):
        return FakeTransaction()

    async def fetchrow(self, query, *args):
        self.executed.append(("fetchrow", query, args))
        return self.session

    async def execute(self, query, *args):
        self.executed.append(("execute", query, args))
        return "UPDATE 1"


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


def request_with_admin_scope():
    return SimpleNamespace(
        state=SimpleNamespace(role="admin", actor_type="user", user_id="ken")
    )


@pytest.mark.asyncio
async def test_start_session_starts_temporal_workflow_and_persists_run_id(monkeypatch):
    conn = FakeConn(
        session={
            "id": 7,
            "status": "pending",
            "trigger": "manual",
            "goal_type": "default",
            "goal_text": "Run D3.3",
            "prompt_version": "v1",
            "recent_context": None,
            "prior_lessons": None,
        }
    )
    pool = FakePool(conn)
    started_inputs = []

    async def fake_start(session):
        started_inputs.append(session)
        return DreamWorkflowStart(workflow_id="dream-session-7", run_id="run-7")

    monkeypatch.setattr(dream_route, "get_pool", lambda: pool)
    monkeypatch.setattr(dream_route, "start_dream_session_workflow", fake_start)

    response = await dream_route.start_session(request_with_admin_scope(), 7)

    assert response == {
        "session_id": 7,
        "status": "running",
        "temporal_workflow_id": "dream-session-7",
        "temporal_run_id": "run-7",
    }
    assert started_inputs[0].session_id == "7"
    assert started_inputs[0].user_id == "ken"
    assert started_inputs[0].trigger == "manual"
    assert started_inputs[0].prompt == "Run D3.3"
    assert started_inputs[0].goal_type == "default"
    assert started_inputs[0].prompt_version == "v1"

    updates = [entry for entry in conn.executed if entry[0] == "execute"]
    assert any("temporal_workflow_id" in query for _, query, _ in updates)
    assert any("temporal_run_id" in query for _, query, _ in updates)


@pytest.mark.asyncio
async def test_start_session_rolls_back_reservation_on_duplicate_workflow(monkeypatch):
    conn = FakeConn(
        session={
            "id": 9,
            "status": "pending",
            "trigger": "manual",
            "goal_type": "default",
            "goal_text": "Run D3.3",
            "prompt_version": "v1",
            "recent_context": None,
            "prior_lessons": None,
        }
    )
    pool = FakePool(conn)

    async def fake_start(session):
        raise WorkflowAlreadyStartedError("dream-session-9", "DreamSessionWorkflow")

    monkeypatch.setattr(dream_route, "get_pool", lambda: pool)
    monkeypatch.setattr(dream_route, "start_dream_session_workflow", fake_start)

    with pytest.raises(HTTPException) as exc:
        await dream_route.start_session(request_with_admin_scope(), 9)

    assert exc.value.status_code == 409
    rollback_updates = [
        query
        for kind, query, _ in conn.executed
        if kind == "execute" and "started_at = NULL" in query
    ]
    assert rollback_updates
