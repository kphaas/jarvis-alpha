from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from brain.routes import rotation
from brain.services.key_rotation import RotateRequest


@asynccontextmanager
async def _fake_conn(*args, **kwargs):
    yield object()


class FakeRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def run(self, conn, invocation, *, payload):
        self.calls.append((conn, invocation, payload))
        return self.result


@pytest.mark.asyncio
async def test_keyturner_rotation_route_queues_approval(monkeypatch):
    runner = FakeRunner(
        SimpleNamespace(
            requires_approval=True,
            denied=False,
            approval_queue_id="queue-1",
            approval_status="pending",
            decision=SimpleNamespace(reason="t4_approval_required"),
            output=None,
        )
    )
    monkeypatch.setattr(rotation, "build_skill_runner", lambda: runner)
    monkeypatch.setattr(rotation, "get_pool", lambda: object())
    monkeypatch.setattr(rotation, "platform_admin_connection", _fake_conn)

    result = await rotation.rotate_key(
        RotateRequest(key_name="ANTHROPIC_API_KEY", new_value="sk-ant-" + "x" * 40)
    )

    assert result.status == "approval_required"
    assert result.approval_queue_id == "queue-1"
    assert result.key_name == "ANTHROPIC_API_KEY"
    assert runner.calls[0][1].agent_id == "keyturner"
    assert runner.calls[0][1].skill_name == "secrets.rotate"
    assert runner.calls[0][2]["rotation_id"] == result.rotation_id
    assert "sk-ant-" not in repr(result)


@pytest.mark.asyncio
async def test_keyturner_rotation_route_returns_executed_result(monkeypatch):
    runner = FakeRunner(
        SimpleNamespace(
            requires_approval=False,
            denied=False,
            approval_queue_id="queue-2",
            approval_status="approved_consumed",
            decision=SimpleNamespace(reason="policy_ok"),
            output={
                "status": "success",
                "rotation_id": "rotation-abc",
                "key_name": "ANTHROPIC_API_KEY",
                "old_key_health": "HTTP 200",
                "new_key_health": "HTTP 200",
            },
        )
    )
    monkeypatch.setattr(rotation, "build_skill_runner", lambda: runner)
    monkeypatch.setattr(rotation, "get_pool", lambda: object())
    monkeypatch.setattr(rotation, "platform_admin_connection", _fake_conn)

    result = await rotation.rotate_key(
        RotateRequest(key_name="ANTHROPIC_API_KEY", new_value="sk-ant-" + "x" * 40)
    )

    assert result.status == "success"
    assert result.rotation_id == "rotation-abc"
    assert result.approval_queue_id == "queue-2"
    assert result.approval_status == "approved_consumed"
