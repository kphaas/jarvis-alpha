from __future__ import annotations

import pytest

from brain.services.memory_graph_extraction import (
    GRAPH_EXTRACTION_PIPELINE,
    build_memory_graph_extraction_records,
    create_memory_graph_extraction_proposals,
)


class FakeGraphConn:
    def __init__(
        self,
        *,
        existing: bool = False,
        active_entity: bool = False,
    ) -> None:
        self.existing = existing
        self.active_entity = active_entity
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        if "alpha_memory_graph_nodes" in query:
            if self.active_entity:
                return {"object_id": "55555555-5555-4555-8555-555555555555"}
            return None
        if not self.existing:
            return None
        return {
            "proposal_id": "33333333-3333-4333-8333-333333333333",
            "status": "queued",
            "approval_queue_id": "44444444-4444-4444-8444-444444444444",
            "parameters_hash": "a" * 64,
        }

    async def fetchval(self, query: str, *args: object):
        self.fetchval_calls.append((query, args))
        return {
            "status": "queued",
            "proposal_id": "11111111-1111-4111-8111-111111111111",
            "approval_queue_id": "22222222-2222-4222-8222-222222222222",
            "parameters_hash": "b" * 64,
        }


def test_graph_extraction_builds_dream_and_buddy_records_without_event_body() -> None:
    records = build_memory_graph_extraction_records(
        _report(),
        buddy_events=[
            {
                "id": "buddy-1",
                "event_type": "alert",
                "title": "Memory review spike",
                "body": "this body must not be persisted",
                "priority": 3,
                "source": "memory_observability_monitor",
                "payload": {"proposal_id": "proposal-1"},
            }
        ],
    )

    assert [record.source_kind for record in records] == ["dream", "dream", "buddy"]
    assert all(record.object_type == "node" for record in records)
    assert records[0].payload["source"] == "dream"
    assert records[0].payload["node_type"] == "fact"
    assert records[1].payload["node_type"] == "task"
    assert records[2].payload["source"] == "buddy"
    assert records[2].payload["external_ref_type"] == "alpha_buddy_events"
    assert GRAPH_EXTRACTION_PIPELINE in str(records[0].payload["provenance"])
    assert records[0].entity_type == "fact"
    assert len(records[0].entity_key) == 64
    assert (
        records[0].payload["properties"]["entity_resolution"]["method"]
        == "label_hash_v1"
    )
    assert records[0].payload["provenance"]["entity_key"] == records[0].entity_key
    assert "this body must not be persisted" not in str(records)


def test_graph_extraction_skips_decay_and_duplicate_candidates() -> None:
    records = build_memory_graph_extraction_records(_report())

    assert {record.source_candidate_id for record in records} == {
        "dream:promote-1",
        "dream:proc-1",
    }
    assert "decay-1" not in str(records)
    assert "dup-1" not in str(records)


@pytest.mark.asyncio
async def test_graph_extraction_reuses_existing_open_proposal() -> None:
    conn = FakeGraphConn(existing=True)

    proposals = await create_memory_graph_extraction_proposals(
        conn,  # type: ignore[arg-type]
        report=_report(),
        actor_sub="ken",
    )

    assert proposals[0].existing is True
    assert proposals[0].proposal_id == "33333333-3333-4333-8333-333333333333"
    assert proposals[0].existing_object_id is None
    assert conn.fetchval_calls == []


@pytest.mark.asyncio
async def test_graph_extraction_reuses_active_entity_without_queueing() -> None:
    conn = FakeGraphConn(active_entity=True)

    proposals = await create_memory_graph_extraction_proposals(
        conn,  # type: ignore[arg-type]
        report=_report(),
        actor_sub="ken",
    )

    assert proposals[0].existing is True
    assert proposals[0].proposal_id is None
    assert proposals[0].existing_object_id == "55555555-5555-4555-8555-555555555555"
    assert proposals[0].status == "active"
    assert conn.fetchval_calls == []


@pytest.mark.asyncio
async def test_graph_extraction_queues_new_t5_reviewed_graph_proposal() -> None:
    conn = FakeGraphConn()

    proposals = await create_memory_graph_extraction_proposals(
        conn,  # type: ignore[arg-type]
        report=_report(),
        actor_sub="ken",
    )

    assert proposals[0].existing is False
    assert proposals[0].status == "queued"
    assert proposals[0].approval_queue_id == "22222222-2222-4222-8222-222222222222"
    assert len(proposals[0].entity_key) == 64
    assert proposals[0].entity_type == "fact"
    assert any("propose_memory_graph_write" in call[0] for call in conn.fetchval_calls)
    query, args = conn.fetchval_calls[0]
    assert "propose_memory_graph_write" in query
    assert args[4] == "memory_graph_extraction"
    assert args[5] == "ken"


def _report() -> dict:
    return {
        "user_id": "ken",
        "canonical_user_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "promotion_candidates": [
            {
                "candidate_id": "promote-1",
                "action": "review_for_semantic_promotion",
                "memory_id": "working-1",
                "tier": "working",
                "summary": "Ken prefers concise status dashboards",
                "reason": "high importance",
                "confidence": 0.9,
            }
        ],
        "decay_candidates": [
            {
                "candidate_id": "decay-1",
                "action": "review_for_working_decay",
                "memory_id": "working-2",
                "summary": "stale scratchpad",
            }
        ],
        "semantic_duplicate_groups": [
            {
                "candidate_id": "dup-1",
                "action": "merge_duplicate_semantic",
                "memory_ids": ["semantic-1", "semantic-2"],
                "normalized_fact": "ken likes bullets",
                "count": 2,
            }
        ],
        "procedural_candidates": [
            {
                "candidate_id": "proc-1",
                "action": "review_for_procedural_memory",
                "memory_id": "episodic-1",
                "tier": "episodic",
                "summary": "When Ken says status, generate the dashboard",
                "reason": "procedural or workflow signal",
                "confidence": 0.75,
            }
        ],
    }
