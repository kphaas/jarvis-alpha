from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brain.routes import at0_mail


def _request(scopes: list[str]):
    return SimpleNamespace(
        state=SimpleNamespace(
            actor_type="service",
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
