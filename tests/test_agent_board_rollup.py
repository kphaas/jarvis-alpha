from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from brain.services.agent_board_rollup import sync_work_item_for_task_graph


def _now() -> datetime:
    return datetime(2026, 7, 2, 18, 45, tzinfo=UTC)


@pytest.mark.asyncio
async def test_completed_child_graph_rolls_up_parent_handoff() -> None:
    graph_id = UUID("11111111-1111-4111-8111-111111111111")
    step_id = UUID("22222222-2222-4222-8222-222222222222")
    parent_id = UUID("33333333-3333-4333-8333-333333333333")
    child_id = UUID("44444444-4444-4444-8444-444444444444")
    child_status = "in_progress"
    child_handoff: dict[str, object] = {}
    parent_status = "in_progress"
    parent_handoff: dict[str, object] = {}
    execute_calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeConn:
        async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
            if "FROM public.alpha_task_graphs" in query:
                return {
                    "id": graph_id,
                    "status": "completed",
                    "completed_at": _now(),
                    "updated_at": _now(),
                }
            if "WHERE task_graph_id = $1" in query:
                return {
                    "id": child_id,
                    "title": "Review child",
                    "status": child_status,
                    "metadata": json.dumps(
                        {"delegation": {"parent_work_item_id": str(parent_id)}}
                    ),
                    "handoff": json.dumps(child_handoff),
                    "task_graph_id": graph_id,
                    "blocked_reason": None,
                }
            if "WHERE id = $1" in query and "FOR UPDATE" in query:
                return {
                    "id": parent_id,
                    "title": "Parent",
                    "status": parent_status,
                    "metadata": json.dumps(
                        {"delegation": {"child_work_item_ids": [str(child_id)]}}
                    ),
                    "handoff": json.dumps(parent_handoff),
                }
            raise AssertionError(f"unexpected fetchrow query: {query}")

        async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            if "FROM public.alpha_task_steps" in query:
                return [
                    {
                        "id": step_id,
                        "step_name": "Review child",
                        "step_type": "llm",
                        "status": "completed",
                        "output": json.dumps({"summary": "ready"}),
                        "error_message": None,
                        "completed_at": _now(),
                    }
                ]
            if "FROM public.alpha_agent_work_items wi" in query:
                return [
                    {
                        "id": child_id,
                        "title": "Review child",
                        "role": "review",
                        "status": child_status,
                        "task_graph_id": graph_id,
                        "blocked_reason": None,
                        "handoff": json.dumps(child_handoff),
                        "updated_at": _now(),
                        "task_graph_status": "completed",
                    }
                ]
            raise AssertionError(f"unexpected fetch query: {query}")

        async def execute(self, query: str, *args: object) -> None:
            nonlocal child_status, child_handoff, parent_status, parent_handoff
            execute_calls.append((query, args))
            if (
                "UPDATE public.alpha_agent_work_items" in query
                and "completed_at = CASE" in query
            ):
                child_status = str(args[1])
                child_handoff.update(json.loads(str(args[3])))
            elif (
                "UPDATE public.alpha_agent_work_items" in query
                and "metadata = metadata || $5::jsonb" in query
            ):
                parent_status = str(args[1])
                parent_handoff.update(json.loads(str(args[3])))

    out = await sync_work_item_for_task_graph(
        FakeConn(),
        graph_id,
        actor="alpha_executor",
    )

    assert out is not None
    assert out["status"] == "handoff_ready"
    assert child_status == "handoff_ready"
    assert parent_status == "handoff_ready"
    assert child_handoff["task_graph"]["artifact_refs"] == [
        {
            "kind": "task_step_output",
            "ref": f"task_graph://{graph_id}/steps/{step_id}/output",
            "step_id": str(step_id),
            "step_name": "Review child",
            "step_type": "llm",
        }
    ]
    rollup = parent_handoff["delegation_rollup"]
    assert rollup["child_count"] == 1
    assert rollup["ready_count"] == 1
    assert rollup["children"][0]["artifact_refs"][0]["step_id"] == str(step_id)
    assert sum("alpha_agent_work_item_events" in call[0] for call in execute_calls) == 2


@pytest.mark.asyncio
async def test_non_terminal_graph_does_not_mutate_board() -> None:
    graph_id = UUID("55555555-5555-4555-8555-555555555555")
    execute_calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeConn:
        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            assert "FROM public.alpha_task_graphs" in query
            return {
                "id": graph_id,
                "status": "running",
                "completed_at": None,
                "updated_at": _now(),
            }

        async def execute(self, query: str, *args: object) -> None:
            execute_calls.append((query, args))

    out = await sync_work_item_for_task_graph(
        FakeConn(),
        graph_id,
        actor="alpha_executor",
    )

    assert out is None
    assert execute_calls == []


@pytest.mark.asyncio
async def test_failed_child_graph_blocks_parent_rollup() -> None:
    graph_id = UUID("66666666-6666-4666-8666-666666666666")
    step_id = UUID("77777777-7777-4777-8777-777777777777")
    parent_id = UUID("88888888-8888-4888-8888-888888888888")
    child_id = UUID("99999999-9999-4999-8999-999999999999")
    child_status = "in_progress"
    child_blocked_reason: str | None = None
    child_handoff: dict[str, object] = {}
    parent_status = "in_progress"
    parent_blocked_reason: str | None = None
    parent_handoff: dict[str, object] = {}
    execute_calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeConn:
        async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
            if "FROM public.alpha_task_graphs" in query:
                return {
                    "id": graph_id,
                    "status": "failed",
                    "completed_at": None,
                    "updated_at": _now(),
                }
            if "WHERE task_graph_id = $1" in query:
                return {
                    "id": child_id,
                    "title": "Code child",
                    "status": child_status,
                    "metadata": json.dumps(
                        {"delegation": {"parent_work_item_id": str(parent_id)}}
                    ),
                    "handoff": json.dumps(child_handoff),
                    "task_graph_id": graph_id,
                    "blocked_reason": child_blocked_reason,
                }
            if "WHERE id = $1" in query and "FOR UPDATE" in query:
                return {
                    "id": parent_id,
                    "title": "Parent",
                    "status": parent_status,
                    "metadata": json.dumps(
                        {"delegation": {"child_work_item_ids": [str(child_id)]}}
                    ),
                    "handoff": json.dumps(parent_handoff),
                }
            raise AssertionError(f"unexpected fetchrow query: {query}")

        async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            if "FROM public.alpha_task_steps" in query:
                return [
                    {
                        "id": step_id,
                        "step_name": "Code child",
                        "step_type": "tool",
                        "status": "failed",
                        "output": "{}",
                        "error_message": "executor timeout",
                        "completed_at": None,
                    }
                ]
            if "FROM public.alpha_agent_work_items wi" in query:
                return [
                    {
                        "id": child_id,
                        "title": "Code child",
                        "role": "code",
                        "status": child_status,
                        "task_graph_id": graph_id,
                        "blocked_reason": child_blocked_reason,
                        "handoff": json.dumps(child_handoff),
                        "updated_at": _now(),
                        "task_graph_status": "failed",
                    }
                ]
            raise AssertionError(f"unexpected fetch query: {query}")

        async def execute(self, query: str, *args: object) -> None:
            nonlocal child_status, child_blocked_reason
            nonlocal parent_status, parent_blocked_reason
            execute_calls.append((query, args))
            if (
                "UPDATE public.alpha_agent_work_items" in query
                and "completed_at = CASE" in query
            ):
                child_status = str(args[1])
                child_blocked_reason = str(args[2])
                child_handoff.update(json.loads(str(args[3])))
            elif (
                "UPDATE public.alpha_agent_work_items" in query
                and "metadata = metadata || $5::jsonb" in query
            ):
                parent_status = str(args[1])
                parent_blocked_reason = str(args[2])
                parent_handoff.update(json.loads(str(args[3])))

    out = await sync_work_item_for_task_graph(
        FakeConn(),
        graph_id,
        actor="alpha_executor",
    )

    assert out is not None
    assert out["status"] == "blocked"
    assert child_status == "blocked"
    assert child_blocked_reason == "executor timeout"
    assert child_handoff["task_graph"]["failed_step_count"] == 1
    assert parent_status == "blocked"
    assert parent_blocked_reason == "executor timeout"
    rollup = parent_handoff["delegation_rollup"]
    assert rollup["blocked_count"] == 1
    assert rollup["pending_count"] == 0
    assert rollup["children"][0]["status"] == "blocked"
    assert sum("alpha_agent_work_item_events" in call[0] for call in execute_calls) == 2
