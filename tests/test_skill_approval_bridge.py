from decimal import Decimal

import pytest

from brain.skills.approval_bridge import (
    SkillApprovalBridge,
    skill_parameters_hash,
)
from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision


def _invocation(**overrides):
    values = {
        "agent_id": "dream_mode",
        "skill_name": "gmail.send",
        "estimated_cost_usd": Decimal("0.01"),
        "idempotency_key": "dream-send-1",
    }
    values.update(overrides)
    return SkillInvocation(**values)


def _decision(**overrides):
    values = {
        "outcome": "approval_required",
        "reason": "t4_approval_required",
        "agent_id": "dream_mode",
        "skill_name": "gmail.send",
        "approval_tier": "T4",
        "skill_scope": "email.send",
        "estimated_cost_usd": Decimal("0.01"),
    }
    values.update(overrides)
    return SkillPolicyDecision(**values)


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.executes = []
        self.fetchvals = []
        self.fetchrows = []

    def transaction(self):
        return FakeTransaction()

    async def execute(self, query, *args):
        self.executes.append((query, args))
        return "SELECT 1"

    async def fetchrow(self, query, *args):
        self.fetchrows.append((query, args))
        status = args[2]
        queue_id = self.rows.get(status)
        if queue_id is None:
            return None
        return {"id": queue_id}

    async def fetchval(self, query, *args):
        self.fetchvals.append((query, args))
        return "queued-id"


def test_skill_parameters_hash_is_stable_and_ignores_private_payload_keys():
    invocation = _invocation()
    decision = _decision()

    first = skill_parameters_hash(
        invocation,
        decision,
        {"body": "hello", "to": "ken", "_adapter": object()},
    )
    second = skill_parameters_hash(
        invocation,
        decision,
        {"to": "ken", "_adapter": object(), "body": "hello"},
    )
    changed = skill_parameters_hash(
        invocation,
        decision,
        {"to": "ken", "body": "different"},
    )

    assert first == second
    assert first != changed


@pytest.mark.asyncio
async def test_bridge_finds_existing_approved_queue_item():
    conn = FakeConn(rows={"approved": "approved-id"})
    bridge = SkillApprovalBridge(notifier=None)

    item = await bridge.find_approved(conn, _invocation(), _decision(), {"body": "ok"})

    assert item is not None
    assert item.queue_id == "approved-id"
    assert item.status == "approved"
    assert any("set_config('rls.role'" in query for query, _ in conn.executes)


@pytest.mark.asyncio
async def test_bridge_queues_pending_item_and_notifies():
    notifications = []

    async def notifier(**kwargs):
        notifications.append(kwargs)
        return True

    conn = FakeConn()
    bridge = SkillApprovalBridge(notifier=notifier)

    item = await bridge.queue_required(
        conn,
        _invocation(),
        _decision(),
        {"body": "ok"},
    )

    assert item.queue_id == "queued-id"
    assert item.status == "pending"
    assert conn.fetchvals
    assert notifications[0]["queue_id"] == "queued-id"
    assert notifications[0]["method"] == "SKILL"
    assert notifications[0]["path"] == "gmail.send"
    assert notifications[0]["actor_sub"] == "agent:dream_mode"
    assert notifications[0]["actor_type"] == "agent"
    assert notifications[0]["action_classes"] == ["agent_skill", "dream_autonomous"]


@pytest.mark.asyncio
async def test_bridge_reuses_existing_pending_item_without_duplicate_notify():
    notifications = []

    async def notifier(**kwargs):
        notifications.append(kwargs)
        return True

    conn = FakeConn(rows={"pending": "pending-id"})
    bridge = SkillApprovalBridge(notifier=notifier)

    item = await bridge.queue_required(
        conn,
        _invocation(),
        _decision(),
        {"body": "ok"},
    )

    assert item.queue_id == "pending-id"
    assert item.status == "pending"
    assert conn.fetchvals == []
    assert notifications == []


@pytest.mark.asyncio
async def test_bridge_consumes_after_successful_skill_execution():
    conn = FakeConn()
    bridge = SkillApprovalBridge(notifier=None)

    await bridge.consume(conn, "approved-id")

    assert conn.executes[-1][0].startswith("SELECT public.consume_approved_queue_item")
    assert conn.executes[-1][1] == ("approved-id",)
