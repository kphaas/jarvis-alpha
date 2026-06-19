from __future__ import annotations

from uuid import uuid4

import pytest

from brain.services.internet_scout import browser_approvals
from brain.services.internet_scout.browser_approvals import (
    BrowserApprovalError,
    browser_task_approval_description,
    browser_task_approval_preview,
    browser_task_parameters_hash,
    enqueue_browser_task_approval,
    consume_browser_task_approval,
    require_approved_browser_task,
)
from brain.services.internet_scout.models import (
    InternetScoutRequest,
    InternetTool,
)
from brain.services.internet_scout.policy import evaluate_policy


def test_browser_task_hash_is_stable_and_description_omits_raw_task_text():
    request = InternetScoutRequest(
        query="open example and click the pricing tab",
        urls=["https://public.example.test/start"],
        tool_hint=InternetTool.BROWSER_USE,
        needs_interaction=True,
    )
    decision = evaluate_policy(request)

    first_hash = browser_task_parameters_hash(request, decision)
    second_hash = browser_task_parameters_hash(request, decision)
    description = browser_task_approval_description(request, decision)

    assert first_hash == second_hash
    assert len(first_hash) == 64
    assert "pricing tab" not in description
    assert "public.example.test" not in description
    assert "Beacon browser-use approval" in description
    assert "urls=1" in description


def test_browser_task_preview_is_redacted_and_reviewable():
    request = InternetScoutRequest(
        query="reserve a table for Ken at 7pm",
        urls=["https://public.example.test/reserve"],
        tool_hint=InternetTool.BROWSER_USE,
        needs_interaction=True,
        max_pages=2,
    )
    decision = evaluate_policy(request)

    preview = browser_task_approval_preview(request, decision)
    payload = preview.model_dump(mode="json")

    assert payload["kind"] == "beacon_browser_use"
    assert payload["requires_human_approval"] is True
    assert payload["has_query"] is True
    assert payload["url_count"] == 1
    assert payload["max_pages"] == 2
    assert payload["same_host_required"] is True
    assert payload["screenshots_required"] is True
    assert payload["raw_task_text_included"] is False
    assert payload["raw_web_content_is_untrusted"] is True
    assert len(payload["approval_hash_prefix"]) == 12
    assert "7pm" not in str(payload)
    assert "public.example.test" not in str(payload)


@pytest.mark.asyncio
async def test_enqueue_browser_task_approval_recovers_duplicate_pending(monkeypatch):
    class DuplicatePendingApproval(Exception):
        pass

    existing_queue_id = uuid4()

    class FakeTransaction:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            self.conn.transaction_entries += 1

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeConn:
        transaction_entries = 0
        lookup_args = None

        def transaction(self):
            return FakeTransaction(self)

        async def fetchval(self, query, *args):
            if "enqueue_approval_request" in query:
                raise DuplicatePendingApproval("duplicate")
            if "FROM public.alpha_approval_queue" in query:
                self.lookup_args = args
                return existing_queue_id
            raise AssertionError(query)

    monkeypatch.setattr(
        browser_approvals.asyncpg,
        "UniqueViolationError",
        DuplicatePendingApproval,
    )
    request = InternetScoutRequest(
        query="open example.com",
        tool_hint=InternetTool.BROWSER_USE,
        needs_interaction=True,
    )
    decision = evaluate_policy(request)
    conn = FakeConn()

    queue_id = await enqueue_browser_task_approval(
        conn,
        request=request,
        decision=decision,
        actor_sub="ken",
        actor_type="user",
        nonce="nonce",
    )

    assert queue_id == existing_queue_id
    assert conn.transaction_entries == 1
    assert conn.lookup_args[0] == "ken"
    assert len(conn.lookup_args[1]) == 64


@pytest.mark.asyncio
async def test_require_approved_browser_task_checks_exact_queue_row():
    queue_id = uuid4()

    class FakeConn:
        async def fetchrow(self, query, *args):
            self.query = query
            self.args = args
            return {"id": queue_id}

    conn = FakeConn()
    await require_approved_browser_task(
        conn,
        approval_queue_id=queue_id,
        actor_sub="ken",
        parameters_hash="a" * 64,
    )

    assert "status = 'approved'" in conn.query
    assert "expires_at > NOW()" in conn.query
    assert conn.args == (queue_id, "ken", "a" * 64)


@pytest.mark.asyncio
async def test_require_approved_browser_task_rejects_missing_row():
    class FakeConn:
        async def fetchrow(self, query, *args):
            return None

    with pytest.raises(BrowserApprovalError) as exc:
        await require_approved_browser_task(
            FakeConn(),
            approval_queue_id=uuid4(),
            actor_sub="ken",
            parameters_hash="a" * 64,
        )

    assert str(exc.value) == "browser_task_approval_not_found"


@pytest.mark.asyncio
async def test_consume_browser_task_approval_uses_secdef_consumer():
    queue_id = uuid4()

    class FakeConn:
        async def execute(self, query, *args):
            self.query = query
            self.args = args

    conn = FakeConn()
    await consume_browser_task_approval(conn, approval_queue_id=queue_id)

    assert "consume_approved_queue_item" in conn.query
    assert conn.args == (queue_id,)
