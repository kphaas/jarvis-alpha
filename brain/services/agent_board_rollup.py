"""Agent Board delegation roll-up helpers."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

TERMINAL_GRAPH_STATUSES = {"completed", "failed", "cancelled"}
READY_CHILD_STATUSES = {"handoff_ready", "done"}
BLOCKED_CHILD_STATUSES = {"blocked", "cancelled"}


def _jsonb_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return dict(value)


def _uuid_list(values: Any) -> list[UUID]:
    if not isinstance(values, list):
        return []
    return [UUID(str(value)) for value in values]


def _delegation_metadata(row: Any) -> dict[str, Any]:
    metadata = _jsonb_dict(row["metadata"])
    delegation = metadata.get("delegation")
    return delegation if isinstance(delegation, dict) else {}


def _step_artifact_refs(graph_id: UUID, steps: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for step in steps:
        if step["status"] != "completed":
            continue
        refs.append(
            {
                "kind": "task_step_output",
                "ref": f"task_graph://{graph_id}/steps/{step['id']}/output",
                "step_id": str(step["id"]),
                "step_name": step["step_name"],
                "step_type": step["step_type"],
            }
        )
    return refs


def _step_outputs(steps: list[Any]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for step in steps:
        if step["status"] != "completed":
            continue
        outputs.append(
            {
                "step_id": str(step["id"]),
                "step_name": step["step_name"],
                "output": _jsonb_dict(step["output"]),
            }
        )
    return outputs


async def sync_work_item_for_task_graph(
    conn: Any,
    graph_id: UUID,
    *,
    actor: str,
) -> dict[str, Any] | None:
    graph = await conn.fetchrow(
        """
        SELECT id, status, completed_at, updated_at
          FROM public.alpha_task_graphs
         WHERE id = $1
        """,
        graph_id,
    )
    if graph is None or graph["status"] not in TERMINAL_GRAPH_STATUSES:
        return None

    work_item = await conn.fetchrow(
        """
        SELECT id, title, status, metadata, handoff, task_graph_id, blocked_reason
          FROM public.alpha_agent_work_items
         WHERE task_graph_id = $1
         FOR UPDATE
        """,
        graph_id,
    )
    if work_item is None:
        return None

    steps = await conn.fetch(
        """
        SELECT id, step_name, step_type, status, output, error_message, completed_at
          FROM public.alpha_task_steps
         WHERE graph_id = $1
         ORDER BY step_order ASC, id ASC
        """,
        graph_id,
    )
    failed_steps = [
        step
        for step in steps
        if step["status"] in {"failed", "cancelled"}
        or (step["error_message"] is not None and step["status"] != "completed")
    ]
    artifact_refs = _step_artifact_refs(graph_id, steps)
    handoff_patch = {
        "task_graph": {
            "id": str(graph_id),
            "status": graph["status"],
            "artifact_refs": artifact_refs,
            "outputs": _step_outputs(steps),
            "step_count": len(steps),
            "completed_step_count": len(artifact_refs),
            "failed_step_count": len(failed_steps),
        }
    }
    if graph["status"] == "completed":
        next_status = (
            work_item["status"]
            if work_item["status"] in {"done", "cancelled"}
            else "handoff_ready"
        )
        blocked_reason = None
    elif graph["status"] == "cancelled":
        next_status = "cancelled"
        blocked_reason = None
    else:
        next_status = "blocked"
        first_error = next(
            (
                str(step["error_message"])
                for step in failed_steps
                if step["error_message"]
            ),
            "delegated task graph failed",
        )
        blocked_reason = first_error[:1000]

    await conn.execute(
        """
        UPDATE public.alpha_agent_work_items
           SET status = $2,
               blocked_reason = $3,
               handoff = handoff || $4::jsonb,
               completed_at = CASE
                 WHEN $2 IN ('done', 'cancelled') THEN NOW()
                 ELSE completed_at
               END,
               updated_at = NOW()
         WHERE id = $1
        """,
        work_item["id"],
        next_status,
        blocked_reason,
        json.dumps(handoff_patch),
    )
    await conn.execute(
        """
        INSERT INTO public.alpha_agent_work_item_events (
            work_item_id, event_type, actor, from_status, to_status, message, metadata
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        """,
        work_item["id"],
        "handoff" if next_status == "handoff_ready" else "status_changed",
        actor,
        work_item["status"],
        next_status,
        "task graph output synced to Agent Board handoff",
        json.dumps(handoff_patch["task_graph"]),
    )

    delegation = _delegation_metadata(work_item)
    parent_id = delegation.get("parent_work_item_id")
    parent_rollup = None
    if parent_id:
        parent_rollup = await roll_up_delegated_parent(
            conn,
            UUID(str(parent_id)),
            actor=actor,
        )

    return {
        "work_item_id": str(work_item["id"]),
        "task_graph_id": str(graph_id),
        "status": next_status,
        "artifact_refs": artifact_refs,
        "parent_rollup": parent_rollup,
    }


async def roll_up_delegated_parent(
    conn: Any,
    parent_work_item_id: UUID,
    *,
    actor: str,
) -> dict[str, Any]:
    parent = await conn.fetchrow(
        """
        SELECT id, title, status, metadata, handoff
          FROM public.alpha_agent_work_items
         WHERE id = $1
         FOR UPDATE
        """,
        parent_work_item_id,
    )
    if parent is None:
        return {"rolled_up": False, "reason": "parent_not_found"}

    delegation = _delegation_metadata(parent)
    child_ids = _uuid_list(delegation.get("child_work_item_ids"))
    if not child_ids:
        return {"rolled_up": False, "reason": "no_delegated_children"}

    children = await conn.fetch(
        """
        SELECT wi.id, wi.title, wi.role, wi.status, wi.task_graph_id,
               wi.blocked_reason, wi.handoff, wi.updated_at,
               g.status AS task_graph_status
          FROM public.alpha_agent_work_items wi
          LEFT JOIN public.alpha_task_graphs g
            ON g.id = wi.task_graph_id
         WHERE wi.id = ANY($1::uuid[])
         ORDER BY wi.created_at ASC
        """,
        child_ids,
    )
    ready_count = sum(
        1 for child in children if child["status"] in READY_CHILD_STATUSES
    )
    blocked_count = sum(
        1 for child in children if child["status"] in BLOCKED_CHILD_STATUSES
    )
    pending_count = max(0, len(children) - ready_count - blocked_count)

    child_summaries: list[dict[str, Any]] = []
    for child in children:
        handoff = _jsonb_dict(child["handoff"])
        task_graph = handoff.get("task_graph")
        artifact_refs = (
            task_graph.get("artifact_refs", []) if isinstance(task_graph, dict) else []
        )
        child_summaries.append(
            {
                "id": str(child["id"]),
                "title": child["title"],
                "role": child["role"],
                "status": child["status"],
                "task_graph_id": str(child["task_graph_id"])
                if child["task_graph_id"]
                else None,
                "task_graph_status": child["task_graph_status"],
                "blocked_reason": child["blocked_reason"],
                "artifact_refs": artifact_refs,
            }
        )

    if blocked_count:
        next_status = "blocked"
        blocked_reason = next(
            (
                child["blocked_reason"] or f"delegated child blocked: {child['title']}"
                for child in children
                if child["status"] in BLOCKED_CHILD_STATUSES
            ),
            "delegated child blocked",
        )[:1000]
    elif children and ready_count == len(children):
        next_status = "handoff_ready"
        blocked_reason = None
    else:
        next_status = (
            "in_progress" if parent["status"] == "queued" else parent["status"]
        )
        blocked_reason = None

    rollup = {
        "child_count": len(children),
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "pending_count": pending_count,
        "children": child_summaries,
    }
    handoff_patch = {"delegation_rollup": rollup}
    delegation_patch = {
        "delegation": {
            **delegation,
            "last_rollup": {
                "child_count": len(children),
                "ready_count": ready_count,
                "blocked_count": blocked_count,
                "pending_count": pending_count,
                "rolled_up_by": actor,
            },
        }
    }
    await conn.execute(
        """
        UPDATE public.alpha_agent_work_items
           SET status = $2,
               blocked_reason = $3,
               handoff = handoff || $4::jsonb,
               metadata = metadata || $5::jsonb,
               updated_at = NOW()
         WHERE id = $1
        """,
        parent["id"],
        next_status,
        blocked_reason,
        json.dumps(handoff_patch),
        json.dumps(delegation_patch),
    )
    await conn.execute(
        """
        INSERT INTO public.alpha_agent_work_item_events (
            work_item_id, event_type, actor, from_status, to_status, message, metadata
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        """,
        parent["id"],
        "handoff" if next_status == "handoff_ready" else "status_changed",
        actor,
        parent["status"],
        next_status,
        "delegated child work items rolled up",
        json.dumps(rollup),
    )
    return {"rolled_up": True, "status": next_status, **rollup}
