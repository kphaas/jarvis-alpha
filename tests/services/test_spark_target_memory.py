from __future__ import annotations

from pathlib import Path

import pytest

from brain.services.spark_target_memory import (
    fetch_target_memory,
    list_target_memory_proposals,
    propose_target_memory_from_note,
    reject_target_memory_proposal,
    target_memory_prompt_items,
)


def test_target_memory_proposal_persists_hashes_only(tmp_path: Path) -> None:
    proposal = propose_target_memory_from_note(
        principal_id="ken",
        approval_id="ken-imessage-approved-20260605-001",
        target_ref_hash="a" * 64,
        target_label="Sweta",
        kind="open_loop",
        note="Send the camp waiver tonight",
        approval_ref_hash="b" * 64,
        source_reference_hash="c" * 64,
        chat_guid_hash="d" * 64,
        feedback_root=tmp_path,
    )

    assert proposal is not None
    assert proposal.target_label == "Sweta"
    assert proposal.reason == "Marked open loop from selected target thread preview"
    assert proposal.evidence_ref_hash is not None

    proposals = list_target_memory_proposals(
        principal_id="ken",
        target_ref_hash="a" * 64,
        feedback_root=tmp_path,
    )

    assert proposals[0].content == "Send the camp waiver tonight."
    assert proposals[0].approval_ref_hash == "b" * 64
    assert proposals[0].source_reference_hash == "c" * 64
    assert proposals[0].chat_guid_hash == "d" * 64


def test_target_memory_proposals_filter_rejected_ids(tmp_path: Path) -> None:
    proposal = propose_target_memory_from_note(
        principal_id="ken",
        approval_id="ken-imessage-approved-20260605-001",
        target_ref_hash="a" * 64,
        target_label="Sweta",
        kind="preference",
        note="She prefers quick confirmation texts",
        approval_ref_hash="b" * 64,
        source_reference_hash="c" * 64,
        chat_guid_hash="d" * 64,
        feedback_root=tmp_path,
    )
    assert proposal is not None

    reject_result = reject_target_memory_proposal(
        principal_id="ken",
        target_ref_hash="a" * 64,
        proposal_id=proposal.proposal_id,
        rejected_by="ken",
        feedback_root=tmp_path,
    )
    filtered = list_target_memory_proposals(
        principal_id="ken",
        target_ref_hash="a" * 64,
        feedback_root=tmp_path,
    )

    assert reject_result["rejected"] is True
    assert filtered == ()


def test_target_memory_prompt_items_prioritize_open_loops() -> None:
    items = target_memory_prompt_items(
        [
            {
                "kind": "profile_fact",
                "content": "She has camp pickup every Thursday.",
                "source": "thread_mark",
                "importance_score": 0.6,
            },
            {
                "kind": "open_loop",
                "content": "Send the waiver tonight.",
                "source": "thread_mark",
                "importance_score": 0.9,
            },
            {
                "kind": "preference",
                "content": "She prefers direct confirmations.",
                "source": "thread_mark",
                "importance_score": 0.7,
            },
        ]
    )

    assert [item.kind for item in items] == [
        "open_loop",
        "preference",
        "profile_fact",
    ]
    assert items[0].reason == "active open loop for selected target"


@pytest.mark.asyncio
async def test_fetch_target_memory_uses_bounded_reader() -> None:
    conn = _FakeConn()

    rows = await fetch_target_memory(conn, "Ken", "a" * 64, limit=10)

    assert rows == [{"content": "Send the waiver tonight."}]
    assert "public.list_spark_target_memory" in conn.sql
    assert conn.args == ("ken", "a" * 64, 10)


class _FakeConn:
    def __init__(self) -> None:
        self.sql = ""
        self.args: tuple[object, ...] = ()

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        self.sql = sql
        self.args = args
        return [{"content": "Send the waiver tonight."}]
