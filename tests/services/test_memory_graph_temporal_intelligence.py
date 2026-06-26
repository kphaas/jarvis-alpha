from __future__ import annotations

from datetime import UTC, datetime

from brain.services.memory_graph_temporal_intelligence import (
    classify_temporal_graph_row,
    summarize_temporal_graph_rows,
)


def test_summarize_temporal_graph_rows_counts_time_states() -> None:
    now = datetime(2026, 6, 25, tzinfo=UTC)
    nodes = [
        {
            "id": "active",
            "node_type": "person",
            "label_hash": "a",
            "updated_at": "2026-06-24T00:00:00Z",
        },
        {
            "id": "expired",
            "node_type": "fact",
            "label_hash": "b",
            "valid_to": "2026-06-01T00:00:00Z",
        },
        {
            "id": "future",
            "node_type": "project",
            "label_hash": "c",
            "valid_from": "2026-07-01T00:00:00Z",
        },
        {
            "id": "stale",
            "node_type": "fact",
            "label_hash": "d",
            "updated_at": "2025-12-01T00:00:00Z",
        },
    ]
    edges = [
        {
            "id": "edge-active",
            "from_node_id": "active",
            "to_node_id": "future",
            "edge_type": "related_to",
            "updated_at": "2026-06-23T00:00:00Z",
        }
    ]

    summary = summarize_temporal_graph_rows(nodes=nodes, edges=edges, now=now)

    assert summary["active_nodes"] == 1
    assert summary["expired_nodes"] == 1
    assert summary["future_nodes"] == 1
    assert summary["stale_nodes"] == 1
    assert summary["active_edges"] == 1
    assert summary["recent_changes"] == 2


def test_summarize_temporal_graph_rows_flags_superseded_candidates() -> None:
    now = datetime(2026, 6, 25, tzinfo=UTC)
    nodes = [
        {
            "id": "node-1",
            "node_type": "person",
            "label_hash": "same",
            "updated_at": "2026-06-10T00:00:00Z",
        },
        {
            "id": "node-2",
            "node_type": "person",
            "label_hash": "same",
            "updated_at": "2026-06-20T00:00:00Z",
        },
        {
            "id": "node-3",
            "node_type": "project",
            "label_hash": "same",
            "updated_at": "2026-06-20T00:00:00Z",
        },
    ]
    edges = [
        {
            "id": "edge-1",
            "from_node_id": "a",
            "to_node_id": "b",
            "edge_type": "works_on",
        },
        {
            "id": "edge-2",
            "from_node_id": "a",
            "to_node_id": "b",
            "edge_type": "works_on",
        },
        {
            "id": "edge-3",
            "from_node_id": "b",
            "to_node_id": "a",
            "edge_type": "works_on",
        },
    ]

    summary = summarize_temporal_graph_rows(nodes=nodes, edges=edges, now=now)

    assert summary["superseded_node_candidates"] == 1
    assert summary["superseded_edge_candidates"] == 1
    assert summary["conflict_candidates"] == 2


def test_temporal_graph_groups_relationship_conflicts_by_entity_keys() -> None:
    now = datetime(2026, 6, 25, tzinfo=UTC)
    nodes = [
        {
            "id": "trip-1",
            "node_type": "project",
            "label_hash": "hash-a",
            "label_preview": "Ken and Sweta are planning Seattle",
            "properties": {
                "entity_keys": ["person:ken:1", "person:sweta:2"],
                "graph_kind": "planning_trip",
                "temporal_kind": "planned_event",
            },
            "updated_at": "2026-06-20T00:00:00Z",
        },
        {
            "id": "trip-2",
            "node_type": "project",
            "label_hash": "hash-b",
            "label_preview": "Sweta and Ken changed the trip",
            "properties": {
                "relationship_subjects": ["sweta", "ken"],
                "graph_kind": "planning_trip",
                "temporal_kind": "planned_event",
            },
            "updated_at": "2026-06-24T00:00:00Z",
        },
    ]

    first = classify_temporal_graph_row(nodes[0], object_type="node", now=now)
    second = classify_temporal_graph_row(nodes[1], object_type="node", now=now)
    summary = summarize_temporal_graph_rows(nodes=nodes, edges=[], now=now)

    assert first["conflict_key"] == second["conflict_key"]
    assert str(first["conflict_key"]).startswith("node:planning_trip:planned_event:")
    assert summary["superseded_node_candidates"] == 1
    assert summary["conflict_candidates"] == 1


def test_classify_temporal_graph_row_marks_retrieval_currentness() -> None:
    now = datetime(2026, 6, 25, tzinfo=UTC)

    active = classify_temporal_graph_row(
        {
            "id": "active",
            "node_type": "project",
            "label_hash": "active-hash",
            "updated_at": "2026-06-24T00:00:00Z",
        },
        object_type="node",
        now=now,
    )
    stale = classify_temporal_graph_row(
        {
            "id": "stale",
            "node_type": "project",
            "label_hash": "stale-hash",
            "updated_at": "2025-12-01T00:00:00Z",
            "properties": {"refresh_prompt_after_days": 30},
        },
        object_type="node",
        now=now,
    )
    expired = classify_temporal_graph_row(
        {
            "id": "expired-edge",
            "from_node_id": "a",
            "to_node_id": "b",
            "edge_type": "works_on",
            "valid_to": "2026-06-01T00:00:00Z",
        },
        object_type="edge",
        now=now,
    )

    assert active == {
        "temporal_state": "active",
        "retrieval_state": "current",
        "refresh_prompt": None,
        "conflict_key": "node:project:active-hash",
        "review_action": "none",
        "review_priority": "none",
        "review_reason": None,
        "review_due_at": None,
        "open_ended": False,
    }
    assert stale["temporal_state"] == "stale"
    assert stale["retrieval_state"] == "needs_refresh"
    assert stale["refresh_prompt"] == "confirm_still_current"
    assert stale["review_action"] == "refresh"
    assert stale["review_priority"] == "medium"
    assert stale["review_reason"] == "refresh_window_elapsed"
    assert stale["review_due_at"] == "2025-12-31T00:00:00Z"
    assert expired["retrieval_state"] == "historical"
    assert expired["refresh_prompt"] == "expired_window"
    assert expired["review_action"] == "keep_historical"
    assert expired["conflict_key"] == "edge:a:b:works_on"


def test_classify_temporal_graph_row_routes_historical_currentness_to_refresh() -> None:
    now = datetime(2026, 6, 25, tzinfo=UTC)

    row = classify_temporal_graph_row(
        {
            "id": "old-trip",
            "node_type": "project",
            "label_hash": "old-trip-hash",
            "updated_at": "2026-06-24T00:00:00Z",
            "properties": {
                "temporal_kind": "planned_event",
                "currentness_policy": "historical_needs_confirmation",
            },
        },
        object_type="node",
        now=now,
    )

    assert row["temporal_state"] == "active"
    assert row["retrieval_state"] == "needs_refresh"
    assert row["refresh_prompt"] == "confirm_currentness"
    assert row["review_action"] == "confirm_currentness"
    assert row["review_reason"] == "historical_fact_needs_confirmation"


def test_classify_temporal_graph_row_flags_conflict_and_open_ended_workflow() -> None:
    now = datetime(2026, 6, 25, tzinfo=UTC)

    row = classify_temporal_graph_row(
        {
            "id": "relationship",
            "node_type": "relationship",
            "label_hash": "relationship-hash",
            "updated_at": "2026-06-20T00:00:00Z",
            "properties": {
                "temporal_kind": "relationship_state",
                "currentness_policy": "candidate_current",
                "requires_operator_resolution": True,
                "refresh_prompt_after_days": 90,
            },
        },
        object_type="node",
        now=now,
    )

    assert row["temporal_state"] == "active"
    assert row["retrieval_state"] == "current"
    assert row["review_action"] == "resolve_conflict"
    assert row["review_priority"] == "high"
    assert row["review_reason"] == "operator_resolution_required"
    assert row["review_due_at"] == "2026-06-25T00:00:00Z"
    assert row["open_ended"] is True


def test_classify_temporal_graph_row_prompts_open_ended_refresh() -> None:
    now = datetime(2026, 6, 25, tzinfo=UTC)

    row = classify_temporal_graph_row(
        {
            "id": "project",
            "node_type": "project",
            "label_hash": "project-hash",
            "updated_at": "2026-06-20T00:00:00Z",
            "properties": {
                "temporal_kind": "project_state",
                "currentness_policy": "candidate_current",
                "refresh_prompt_after_days": 60,
            },
        },
        object_type="node",
        now=now,
    )

    assert row["review_action"] == "refresh"
    assert row["review_priority"] == "medium"
    assert row["review_reason"] == "open_ended_current_fact"
    assert row["review_due_at"] == "2026-08-19T00:00:00Z"
    assert row["open_ended"] is True
