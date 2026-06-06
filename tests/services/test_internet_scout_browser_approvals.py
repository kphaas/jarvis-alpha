from __future__ import annotations

from uuid import uuid4

import pytest

from brain.services.internet_scout.browser_approvals import (
    BrowserApprovalError,
    browser_task_approval_description,
    browser_task_parameters_hash,
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
