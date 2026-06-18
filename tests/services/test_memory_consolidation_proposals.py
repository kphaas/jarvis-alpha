from __future__ import annotations

from uuid import UUID

import pytest

from brain.services.memory_consolidation_proposals import (
    EXECUTABLE_ACTIONS,
    INFORMATIONAL_ACTIONS,
    MEMORY_CONSOLIDATION_APPROVAL_ACTION_CLASSES,
    MEMORY_CONSOLIDATION_APPROVAL_TIER,
    UnknownConsolidationActionError,
    build_memory_consolidation_proposal_records,
    create_reviewed_memory_consolidation_proposals,
    enqueue_memory_consolidation_approval,
    expire_stale_memory_consolidation_proposals,
)


class FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchval(self, query: str, *args: object):
        self.calls.append((query, args))
        return UUID("11111111-1111-4111-8111-111111111111")


class FakeProposalConn:
    def __init__(self) -> None:
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        return {
            "id": "22222222-2222-4222-8222-222222222222",
            "status": "pending_review",
            "executable": True,
            "approval_queue_id": None,
        }

    async def fetchval(self, query: str, *args: object):
        self.fetchval_calls.append((query, args))
        if "mark_memory_consolidation_archive_hold" in query:
            return 1
        return UUID("11111111-1111-4111-8111-111111111111")

    async def execute(self, query: str, *args: object):
        self.execute_calls.append((query, args))
        return "UPDATE 1"


def test_proposal_records_are_deterministic_and_idempotent() -> None:
    report = _report()

    first = build_memory_consolidation_proposal_records(report)
    second = build_memory_consolidation_proposal_records(report)

    assert first == second
    assert [record.parameters_hash for record in first] == [
        record.parameters_hash for record in second
    ]
    assert len({record.parameters_hash for record in first}) == len(first)


def test_only_promotion_and_working_decay_are_executable() -> None:
    records = build_memory_consolidation_proposal_records(_report())
    by_action = {record.candidate_action: record for record in records}

    assert set(EXECUTABLE_ACTIONS) == {
        "review_for_semantic_promotion",
        "review_for_working_decay",
    }
    assert set(INFORMATIONAL_ACTIONS) == {
        "merge_duplicate_semantic",
        "review_for_procedural_memory",
    }
    assert by_action["review_for_semantic_promotion"].executable is True
    assert (
        by_action["review_for_semantic_promotion"].proposed_action
        == "promote_episodic_to_semantic"
    )
    assert by_action["review_for_working_decay"].executable is True
    assert by_action["review_for_working_decay"].proposed_action == "archive_working"
    assert by_action["merge_duplicate_semantic"].executable is False
    assert by_action["merge_duplicate_semantic"].initial_status == "informational"
    assert by_action["review_for_procedural_memory"].executable is False
    assert by_action["review_for_procedural_memory"].initial_status == "informational"


def test_unknown_candidate_action_fails_closed() -> None:
    report = _report()
    report["promotion_candidates"] = [
        {
            "candidate_id": "bad",
            "action": "write_whatever",
            "memory_id": "m1",
        }
    ]

    with pytest.raises(UnknownConsolidationActionError):
        build_memory_consolidation_proposal_records(report)


@pytest.mark.asyncio
async def test_archive_proposal_marks_buddy_hold_after_queueing() -> None:
    report = _report()
    report["promotion_candidates"] = []
    report["semantic_duplicate_groups"] = []
    report["procedural_candidates"] = []
    conn = FakeProposalConn()

    proposals = await create_reviewed_memory_consolidation_proposals(
        conn,  # type: ignore[arg-type]
        report=report,
        actor_sub="ken",
        actor_type="user",
    )

    assert len(proposals) == 1
    assert proposals[0].proposed_action == "archive_working"
    assert proposals[0].status == "queued"
    assert "expire_stale_memory_consolidation_proposals" in conn.fetchval_calls[0][0]
    assert any(
        "enqueue_approval_request" in query for query, _args in conn.fetchval_calls
    )
    assert any(
        "mark_memory_consolidation_archive_hold" in query
        for query, _args in conn.fetchval_calls
    )


@pytest.mark.asyncio
async def test_enqueue_memory_consolidation_approval_is_t5_without_memory_text():
    record = build_memory_consolidation_proposal_records(_report())[0]
    conn = FakeConn()

    queue_id = await enqueue_memory_consolidation_approval(
        conn,  # type: ignore[arg-type]
        proposal_id="22222222-2222-4222-8222-222222222222",
        record=record,
        actor_sub="ken",
        actor_type="user",
    )

    assert str(queue_id) == "11111111-1111-4111-8111-111111111111"
    assert len(conn.calls) == 1
    query, args = conn.calls[0]
    assert "enqueue_approval_request" in query
    assert args[0] == list(MEMORY_CONSOLIDATION_APPROVAL_ACTION_CLASSES)
    assert args[1] == MEMORY_CONSOLIDATION_APPROVAL_TIER
    assert args[2] == "ken"
    assert args[3] == "user"
    assert (
        args[4]
        == "Memory consolidation reviewed write: promote_episodic_to_semantic for 1 source item(s)"
    )
    assert args[5] == record.parameters_hash
    assert "private Spark voice text" not in str(args)


@pytest.mark.asyncio
async def test_expire_stale_memory_consolidation_proposals_uses_secdef_function():
    conn = FakeConn()

    await expire_stale_memory_consolidation_proposals(conn)  # type: ignore[arg-type]

    assert len(conn.calls) == 1
    assert "expire_stale_memory_consolidation_proposals" in conn.calls[0][0]


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
                "summary": "private Spark voice text",
                "reason": "high importance",
                "confidence": 0.9,
            }
        ],
        "decay_candidates": [
            {
                "candidate_id": "decay-1",
                "action": "review_for_working_decay",
                "memory_id": "working-2",
                "tier": "working",
                "summary": "stale private working text",
                "reason": "working memory older than 20h",
                "confidence": 0.8,
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
                "summary": "workflow signal",
                "reason": "procedural or workflow signal",
                "confidence": 0.75,
            }
        ],
    }
