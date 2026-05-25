"""Tests for Dream Mode Temporal workflow registration."""

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from brain.dream import client as dream_client
from brain.dream.activities import (
    flush_cleanup_activity,
    persist_plan_activity,
    plan_session_activity,
    review_plan_activity,
)
from brain.dream.client import (
    dream_workflow_id,
    start_dream_session_workflow,
    temporal_namespace,
    temporal_target,
)
from brain.dream.task_queues import DREAM_WORKFLOW_QUEUE, PLANNING_QUEUE
from brain.dream.types import DreamSessionInput
from brain.dream.worker import (
    TEMPORAL_ACTIVITIES,
    TEMPORAL_WORKFLOWS,
)
from brain.dream.workflows import (
    DreamSessionWorkflow,
    FLUSH_CLEANUP_START_TO_CLOSE,
    PERSIST_PLAN_START_TO_CLOSE,
    PLAN_START_TO_CLOSE,
    REVIEW_START_TO_CLOSE,
)


def test_worker_registers_dream_workflow_and_activity():
    assert TEMPORAL_WORKFLOWS == [DreamSessionWorkflow]
    assert TEMPORAL_ACTIVITIES == [
        plan_session_activity,
        review_plan_activity,
        persist_plan_activity,
        flush_cleanup_activity,
    ]
    assert DREAM_WORKFLOW_QUEUE == PLANNING_QUEUE


def test_temporal_target_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("TEMPORAL_BIND_HOST", raising=False)
    monkeypatch.delenv("TEMPORAL_GRPC_PORT", raising=False)
    assert temporal_target() == "127.0.0.1:7233"


def test_temporal_target_uses_env(monkeypatch):
    monkeypatch.setenv("TEMPORAL_BIND_HOST", "127.0.0.2")
    monkeypatch.setenv("TEMPORAL_GRPC_PORT", "7722")
    assert temporal_target() == "127.0.0.2:7722"


def test_temporal_namespace_default(monkeypatch):
    monkeypatch.delenv("TEMPORAL_NAMESPACE", raising=False)
    assert temporal_namespace() == "default"


def test_dream_workflow_id_is_deterministic():
    assert dream_workflow_id(42) == "dream-session-42"
    assert dream_workflow_id("session-a") == "dream-session-session-a"


async def test_start_dream_session_workflow_uses_expected_temporal_options(
    monkeypatch,
):
    calls = {}

    class FakeHandle:
        id = "dream-session-42"
        run_id = "run-abc"

    class FakeClient:
        async def start_workflow(self, workflow, arg, **kwargs):
            calls["workflow"] = workflow
            calls["arg"] = arg
            calls.update(kwargs)
            return FakeHandle()

    async def fake_connect(target, *, namespace):
        calls["target"] = target
        calls["namespace"] = namespace
        return FakeClient()

    monkeypatch.setattr(dream_client.Client, "connect", fake_connect)
    monkeypatch.setenv("TEMPORAL_BIND_HOST", "127.0.0.9")
    monkeypatch.setenv("TEMPORAL_GRPC_PORT", "7999")
    monkeypatch.delenv("TEMPORAL_NAMESPACE", raising=False)

    result = await start_dream_session_workflow(
        DreamSessionInput(session_id="42", user_id="ken", prompt="Run D3.3")
    )

    assert result.workflow_id == "dream-session-42"
    assert result.run_id == "run-abc"
    assert calls["target"] == "127.0.0.9:7999"
    assert calls["namespace"] == "default"
    assert calls["workflow"] is DreamSessionWorkflow.run
    assert calls["arg"].session_id == "42"
    assert calls["id"] == "dream-session-42"
    assert calls["task_queue"] == DREAM_WORKFLOW_QUEUE
    assert calls["id_reuse_policy"] == WorkflowIDReusePolicy.REJECT_DUPLICATE
    assert calls["id_conflict_policy"] == WorkflowIDConflictPolicy.FAIL


def test_workflow_cleanup_timeout_is_bounded():
    assert PLAN_START_TO_CLOSE.total_seconds() == 300
    assert REVIEW_START_TO_CLOSE.total_seconds() == 180
    assert PERSIST_PLAN_START_TO_CLOSE.total_seconds() == 30
    assert FLUSH_CLEANUP_START_TO_CLOSE.total_seconds() == 30
