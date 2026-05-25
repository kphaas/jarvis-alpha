"""Temporal client helpers for Dream Mode."""

from __future__ import annotations

import os
from dataclasses import dataclass

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from brain.dream.task_queues import DREAM_WORKFLOW_QUEUE
from brain.dream.types import DreamSessionInput
from brain.dream.workflows import DreamSessionWorkflow


@dataclass(frozen=True)
class DreamWorkflowStart:
    workflow_id: str
    run_id: str | None


def dream_workflow_id(session_id: int | str) -> str:
    return f"dream-session-{session_id}"


def temporal_target() -> str:
    bind_ip = os.environ.get("TEMPORAL_BIND_IP")
    host = (
        os.environ.get("TEMPORAL_CLIENT_HOST")
        or (bind_ip if bind_ip and bind_ip != "0.0.0.0" else None)
        or os.environ.get("TEMPORAL_BIND_HOST")
        or "127.0.0.1"
    )
    port = os.environ.get("TEMPORAL_GRPC_PORT", "7233")
    return f"{host}:{port}"


def temporal_namespace() -> str:
    return os.environ.get("TEMPORAL_NAMESPACE", "default")


async def start_dream_session_workflow(
    session: DreamSessionInput,
) -> DreamWorkflowStart:
    client = await Client.connect(temporal_target(), namespace=temporal_namespace())
    handle = await client.start_workflow(
        DreamSessionWorkflow.run,
        session,
        id=dream_workflow_id(session.session_id),
        task_queue=DREAM_WORKFLOW_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
    )
    return DreamWorkflowStart(
        workflow_id=handle.id,
        run_id=handle.first_execution_run_id or handle.result_run_id or handle.run_id,
    )
