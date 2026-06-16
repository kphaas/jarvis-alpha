from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import bcrypt
import pytest

from brain.agents.privacy_scrub import drafts
from brain.agents.privacy_scrub.state import StoredDraftAction
from brain.routes import approvals


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        headers={"x-approval-token": "approval-token"},
        state=SimpleNamespace(
            user_id="ken",
            actor_type="user",
            role="admin",
            scopes=[],
            iss="user",
        ),
    )


@asynccontextmanager
async def _transaction():
    yield


@pytest.mark.asyncio
async def test_unlock_approvals_reads_profile_with_request_rls(
    monkeypatch,
    tmp_path,
) -> None:
    pin = "121423"
    pin_hash = bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    calls = SimpleNamespace(request=None, query=None)

    class FakeConn:
        async def fetchrow(self, query, *args):
            calls.query = query
            return {"pin_hash": pin_hash}

    @asynccontextmanager
    async def fake_rls_connection(request):
        calls.request = request
        yield FakeConn()

    private_key = tmp_path / "jwt_private.pem"
    private_key.write_text("private", encoding="utf-8")

    monkeypatch.setenv("ALPHA_JWT_PRIVATE_KEY", str(private_key))
    monkeypatch.setattr(approvals, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(
        approvals.jwt, "encode", lambda *args, **kwargs: "approval-token"
    )

    request = _request()
    response = await approvals.unlock_approvals(
        approvals.UnlockRequest(pin=pin),
        request,
    )

    assert calls.request is request
    assert "alpha_profiles" in calls.query
    assert response == {
        "approval_token": "approval-token",
        "expires_in": 300,
    }


@pytest.mark.asyncio
async def test_pending_approvals_include_privacy_case_context(monkeypatch) -> None:
    queue_id = uuid4()
    case_id = uuid4()

    class FakeConn:
        def __init__(self) -> None:
            self.query = ""

        async def fetch(self, query, *args):
            self.query = query
            return [
                {
                    "id": queue_id,
                    "action_class": ["privacy_draft_handoff", "security_write"],
                    "risk_tier": "T4",
                    "actor_sub": "ken",
                    "actor_type": "user",
                    "description": "Privacy case draft approval handoff",
                    "status": "pending",
                    "requested_at": datetime.now(UTC),
                    "expires_at": datetime.now(UTC) + timedelta(minutes=5),
                    "overnight": False,
                    "privacy_case_id": case_id,
                    "privacy_action_count": 2,
                    "privacy_action_statuses": ["awaiting_approval"],
                }
            ]

    conn = FakeConn()

    @asynccontextmanager
    async def fake_rls_connection(request):
        yield conn

    monkeypatch.setattr(approvals, "rls_connection", fake_rls_connection)

    response = await approvals.list_pending(_request())

    assert "privacy_context" in conn.query
    assert response["count"] == 1
    assert response["pending"][0]["privacy"] == {
        "case_id": str(case_id),
        "action_count": 2,
        "action_statuses": ["awaiting_approval"],
    }
    assert response["pending"][0]["spark"] is None


@pytest.mark.asyncio
async def test_pending_approvals_include_spark_draft_context(monkeypatch) -> None:
    queue_id = uuid4()

    class FakeConn:
        def __init__(self) -> None:
            self.query = ""

        async def fetch(self, query, *args):
            self.query = query
            return [
                {
                    "id": queue_id,
                    "action_class": ["spark_draft_handoff", "security_write"],
                    "risk_tier": "T2",
                    "actor_sub": "spark-service",
                    "actor_type": "service",
                    "description": "Spark iMessage draft approval",
                    "status": "pending",
                    "requested_at": datetime.now(UTC),
                    "expires_at": datetime.now(UTC) + timedelta(minutes=5),
                    "overnight": False,
                    "privacy_case_id": None,
                    "privacy_action_count": None,
                    "privacy_action_statuses": None,
                    "spark_principal_id": None,
                    "spark_target_label": None,
                    "spark_outbox_id": None,
                    "spark_outbox_status": None,
                }
            ]

    conn = FakeConn()

    @asynccontextmanager
    async def fake_rls_connection(request):
        yield conn

    monkeypatch.setattr(approvals, "rls_connection", fake_rls_connection)

    response = await approvals.list_pending(_request())

    assert "spark_context" in conn.query
    assert response["count"] == 1
    assert response["pending"][0]["privacy"] is None
    assert response["pending"][0]["spark"] == {
        "kind": "imessage_draft",
        "can_send": False,
        "requires_human_approval": True,
        "principal_id": None,
        "target_label": None,
        "outbox_id": None,
        "outbox_status": None,
        "outbox_recorded": False,
    }


@pytest.mark.asyncio
async def test_decide_approval_records_privacy_action_decision(
    monkeypatch,
    tmp_path,
) -> None:
    queue_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    calls = SimpleNamespace(record=None)

    class FakeConn:
        def transaction(self):
            return _transaction()

        async def fetch(self, query, *args):
            assert "decide_approval" in query
            assert args[0] == str(queue_id)
            return [
                {
                    "queue_id": queue_id,
                    "action_class": ["privacy_draft_handoff", "security_write"],
                    "risk_tier": "T4",
                    "actor_sub": "ken",
                    "actor_type": "user",
                    "description": "Privacy case draft approval handoff",
                    "parameters_hash": "sha256:" + "1" * 64,
                    "overnight": False,
                    "expires_at": expires_at,
                }
            ]

    @asynccontextmanager
    async def fake_rls_connection(request):
        yield FakeConn()

    async def fake_record_privacy_approval_decision(
        conn,
        *,
        approval_queue_id: UUID,
        decision: str,
        actor: str,
    ):
        calls.record = (approval_queue_id, decision, actor)
        return ()

    pub_key = tmp_path / "jwt_public.pem"
    pub_key.write_text("public", encoding="utf-8")
    monkeypatch.setenv("ALPHA_JWT_PUBLIC_KEY", str(pub_key))
    monkeypatch.setattr(
        approvals.jwt, "decode", lambda *args, **kwargs: {"purpose": "approval"}
    )
    monkeypatch.setattr(approvals, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(
        approvals,
        "record_privacy_approval_decision",
        fake_record_privacy_approval_decision,
    )

    response = await approvals.decide_approval(
        str(queue_id),
        approvals.DecideRequest(decision="approved"),
        _request(),
    )

    assert response["queue_id"] == str(queue_id)
    assert response["decision"] == "approved"
    assert calls.record == (queue_id, "approved", "ken")


@pytest.mark.parametrize(
    ("decision", "status"),
    (
        ("approved", "approved"),
        ("denied", "rejected"),
    ),
)
@pytest.mark.asyncio
async def test_record_privacy_approval_decision_marks_actions_and_appends_event(
    monkeypatch,
    decision,
    status,
) -> None:
    queue_id = uuid4()
    action = StoredDraftAction(
        id=uuid4(),
        subject_id=uuid4(),
        target_id="spokeo",
        case_draft_id=uuid4(),
        action_type="draft",
        approval_tier="T4",
        status=status,
        draft_payload_hash="sha256:" + "1" * 64,
        payload_key_version="payload-v1",
    )
    calls = SimpleNamespace(mark=None, events=[])

    async def fake_mark_approval_queue_actions_decided(
        conn,
        *,
        approval_queue_id,
        status,
    ):
        calls.mark = (approval_queue_id, status)
        return [action]

    async def fake_append_action_event(conn, **kwargs):
        calls.events.append(kwargs)

    monkeypatch.setattr(
        drafts,
        "mark_approval_queue_actions_decided",
        fake_mark_approval_queue_actions_decided,
    )
    monkeypatch.setattr(drafts, "append_action_event", fake_append_action_event)

    result = await drafts.record_privacy_approval_decision(
        SimpleNamespace(),
        approval_queue_id=queue_id,
        decision=decision,
        actor="ken",
    )

    assert result == (action,)
    assert calls.mark == (queue_id, status)
    assert calls.events == [
        {
            "action_id": action.id,
            "event_type": status,
            "actor": "ken",
        }
    ]
