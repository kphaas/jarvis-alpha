from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from brain.routes import at0_mail


def _request(scopes: list[str]):
    return SimpleNamespace(
        state=SimpleNamespace(
            actor_type="service",
            sub="test-actor",
            user_id="test-actor",
            role=None,
            scopes=scopes,
            iss="test",
        )
    )


@pytest.mark.asyncio
async def test_mailboxes_route_returns_configured_mailboxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        at0_mail,
        "_configured_mailboxes",
        lambda: ("hello@at-0.com", "support@at-0.com"),
    )

    response = await at0_mail.get_mailboxes(
        _request(["at0_mail.read"]),
        "user",
    )

    assert response.mailboxes == ["hello@at-0.com", "support@at-0.com"]


@pytest.mark.asyncio
async def test_spark_profile_route_returns_draft_only_profile() -> None:
    response = await at0_mail.get_spark_profile(
        _request(["at0_mail.read"]),
        "user",
    )

    assert response.spark_id == "at0-spark"
    assert response.display_name == "AT-0 Spark"
    assert response.can_send is False
    assert response.requires_human_approval is True


@pytest.mark.asyncio
async def test_scan_can_target_one_configured_mailbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        at0_mail,
        "_configured_mailboxes",
        lambda: ("hello@at-0.com", "support@at-0.com"),
    )

    async def fake_scan_at0_mail(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            scan_run_id="scan-1",
            mailboxes_scanned=1,
            messages_seen=0,
            messages_new=0,
            draft_proposals_created=0,
        )

    monkeypatch.setattr(at0_mail, "scan_at0_mail", fake_scan_at0_mail)

    response = await at0_mail.scan_mailboxes(
        _request(["at0_mail.scan"]),
        "user",
        max_results=10,
        mailbox="HELLO@AT-0.COM",
    )

    assert response.mailboxes_scanned == 1
    assert calls == {
        "max_results": 10,
        "trigger": "api",
        "mailboxes": ("hello@at-0.com",),
    }


@pytest.mark.asyncio
async def test_scan_rejects_unconfigured_mailbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        at0_mail,
        "_configured_mailboxes",
        lambda: ("hello@at-0.com",),
    )

    with pytest.raises(HTTPException) as exc_info:
        await at0_mail.scan_mailboxes(
            _request(["at0_mail.scan"]),
            "user",
            mailbox="other@at-0.com",
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_drafts_can_filter_by_configured_mailbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        at0_mail,
        "_configured_mailboxes",
        lambda: ("hello@at-0.com", "support@at-0.com"),
    )

    class FakeConn:
        async def fetch(self, query: str, *params):
            seen["query"] = query
            seen["params"] = params
            return []

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    monkeypatch.setattr(at0_mail, "get_pool", lambda: FakePool())

    response = await at0_mail.list_drafts(
        _request(["at0_mail.read"]),
        "user",
        status="needs_review",
        mailbox="support@at-0.com",
        limit=50,
    )

    assert response.drafts == []
    assert "d.mailbox = $2" in str(seen["query"])
    assert seen["params"] == ("needs_review", "support@at-0.com", 50)


@pytest.mark.asyncio
async def test_status_update_rejects_sent_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_id = UUID("11111111-1111-4111-8111-111111111111")

    class FakeTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

        async def fetchrow(self, query: str, *params):
            return {"status": "sent"}

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    monkeypatch.setattr(at0_mail, "get_pool", lambda: FakePool())

    with pytest.raises(HTTPException) as exc_info:
        await at0_mail.update_draft_status(
            draft_id,
            at0_mail.At0MailDraftStatusUpdate(status="rejected"),
            _request(["at0_mail.write"]),
            "user",
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_send_draft_reply_requires_prepared_approved_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_id = UUID("11111111-1111-4111-8111-111111111111")
    message_id = UUID("22222222-2222-4222-8222-222222222222")
    calls: dict[str, object] = {}

    class FakeTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    prepared = SimpleNamespace(
        draft_id=draft_id,
        mail_message_id=message_id,
        mailbox="hello@at-0.com",
        graph_message_id="graph-message-1",
        reply_body="Approved reply",
        actor_sub="test-actor",
        actor_type="service",
        send_attempt_count=1,
    )

    async def fake_prepare(conn, **kwargs):
        calls["prepare"] = kwargs
        return prepared

    async def fake_send_at0_mail_reply(**kwargs):
        calls["send"] = kwargs
        return SimpleNamespace(status_code=202, provider_operation="message.reply")

    async def fake_record_success(conn, **kwargs):
        calls["success"] = kwargs
        return SimpleNamespace(
            draft_id=draft_id,
            mail_message_id=message_id,
            mailbox="hello@at-0.com",
            status="sent",
            graph_status_code=202,
            send_attempt_count=1,
            sent_at=datetime(2026, 6, 18, 17, 0, tzinfo=UTC),
        )

    monkeypatch.setattr(at0_mail, "get_pool", lambda: FakePool())
    monkeypatch.setattr(at0_mail, "prepare_at0_mail_reply_send", fake_prepare)
    monkeypatch.setattr(at0_mail, "send_at0_mail_reply", fake_send_at0_mail_reply)
    monkeypatch.setattr(
        at0_mail,
        "record_at0_mail_reply_send_success",
        fake_record_success,
    )

    response = await at0_mail.send_draft_reply(
        draft_id,
        _request(["at0_mail.write"]),
        "user",
    )

    assert response.status == "sent"
    assert response.graph_status_code == 202
    assert calls["prepare"] == {
        "draft_id": draft_id,
        "actor_sub": "test-actor",
        "actor_type": "service",
    }
    assert calls["send"] == {
        "mailbox": "hello@at-0.com",
        "message_id": "graph-message-1",
        "reply_body": "Approved reply",
    }
    assert calls["success"]["prepared"] is prepared


@pytest.mark.asyncio
async def test_send_draft_reply_rejects_unapproved_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_id = UUID("11111111-1111-4111-8111-111111111111")

    class FakeTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    async def fake_prepare(conn, **kwargs):
        raise at0_mail.At0MailDraftNotReadyError("draft_status_needs_review")

    async def fake_send_at0_mail_reply(**kwargs):
        raise AssertionError("send should not be called")

    monkeypatch.setattr(at0_mail, "get_pool", lambda: FakePool())
    monkeypatch.setattr(at0_mail, "prepare_at0_mail_reply_send", fake_prepare)
    monkeypatch.setattr(at0_mail, "send_at0_mail_reply", fake_send_at0_mail_reply)

    with pytest.raises(HTTPException) as exc_info:
        await at0_mail.send_draft_reply(
            draft_id,
            _request(["at0_mail.write"]),
            "user",
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_send_draft_reply_records_graph_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft_id = UUID("11111111-1111-4111-8111-111111111111")
    message_id = UUID("22222222-2222-4222-8222-222222222222")
    calls: dict[str, object] = {}

    class FakeTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    prepared = SimpleNamespace(
        draft_id=draft_id,
        mail_message_id=message_id,
        mailbox="hello@at-0.com",
        graph_message_id="graph-message-1",
        reply_body="Approved reply",
        actor_sub="test-actor",
        actor_type="service",
        send_attempt_count=1,
    )

    async def fake_prepare(conn, **kwargs):
        return prepared

    async def fake_send_at0_mail_reply(**kwargs):
        raise at0_mail.At0MailGraphError(
            "Microsoft Graph reply failed: 403",
            status_code=403,
            error_type="ErrorAccessDenied",
        )

    async def fake_record_failure(conn, **kwargs):
        calls["failure"] = kwargs
        return SimpleNamespace(
            draft_id=draft_id,
            mail_message_id=message_id,
            mailbox="hello@at-0.com",
            status="send_failed",
            graph_status_code=403,
            send_attempt_count=1,
            sent_at=None,
        )

    monkeypatch.setattr(at0_mail, "get_pool", lambda: FakePool())
    monkeypatch.setattr(at0_mail, "prepare_at0_mail_reply_send", fake_prepare)
    monkeypatch.setattr(at0_mail, "send_at0_mail_reply", fake_send_at0_mail_reply)
    monkeypatch.setattr(
        at0_mail,
        "record_at0_mail_reply_send_failure",
        fake_record_failure,
    )

    with pytest.raises(HTTPException) as exc_info:
        await at0_mail.send_draft_reply(
            draft_id,
            _request(["at0_mail.write"]),
            "user",
        )

    assert exc_info.value.status_code == 502
    assert calls["failure"]["prepared"] is prepared
    assert calls["failure"]["status_code"] == 403
