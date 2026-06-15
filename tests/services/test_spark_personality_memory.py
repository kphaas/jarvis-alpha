from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain.services.spark_personality_memory import (
    build_personality_memory_proposals,
    fetch_personality_memory,
    personality_memory_context,
    reject_personality_memory_proposal,
)
from brain.services.spark_persona_guardrails import default_spark_guardrails
from brain.services.spark_voice_feedback import FEEDBACK_FILENAME


def test_personality_memory_proposals_include_guardrails_and_feedback(
    tmp_path: Path,
) -> None:
    _write_feedback(
        tmp_path,
        {
            "feedback_ref_hash": "a" * 64,
            "candidate_key_phrases": [
                "fair enough",
                "private key should not persist",
            ],
            "calibration_lessons": [
                "Prefer shorter text drafts when Spark over-explains.",
                "Avoid formal email-style phrasing in text replies.",
            ],
        },
    )

    proposals = build_personality_memory_proposals(
        principal_id="ken",
        guardrails=default_spark_guardrails(),
        feedback_root=tmp_path,
    )

    contents = [proposal.content for proposal in proposals]
    assert "Voice should feel optimistic." in contents
    assert "Avoid sounding robotic." in contents
    assert "Signature phrase: cheers." in contents
    assert "legal topics require Spark review before action." in contents
    assert any("Sweta: partner" in content for content in contents)
    assert "Candidate phrase from reviewed draft edit: fair enough." in contents
    assert "Prefer shorter text drafts when Spark over-explains." in contents
    assert "Avoid formal email-style phrasing in text replies." in contents
    assert not any("private key" in content for content in contents)
    kinds_by_content = {proposal.content: proposal.kind for proposal in proposals}
    assert (
        kinds_by_content["Prefer shorter text drafts when Spark over-explains."]
        == "style"
    )
    assert (
        kinds_by_content["Avoid formal email-style phrasing in text replies."]
        == "avoid"
    )


def test_personality_memory_proposals_dedupe_active_rows() -> None:
    proposals = build_personality_memory_proposals(
        principal_id="ken",
        guardrails=default_spark_guardrails(),
        existing_rows=[
            {
                "kind": "voice",
                "content": "Voice should feel optimistic.",
            }
        ],
    )

    assert "Voice should feel optimistic." not in [
        proposal.content for proposal in proposals
    ]


def test_rejected_personality_memory_proposal_is_filtered(tmp_path: Path) -> None:
    proposals = build_personality_memory_proposals(
        principal_id="ken",
        guardrails=default_spark_guardrails(),
        feedback_root=tmp_path,
    )
    target = proposals[0]

    result = reject_personality_memory_proposal(
        principal_id="ken",
        proposal_id=target.proposal_id,
        rejected_by="ken",
        feedback_root=tmp_path,
    )
    filtered = build_personality_memory_proposals(
        principal_id="ken",
        guardrails=default_spark_guardrails(),
        feedback_root=tmp_path,
    )

    assert result["rejected"] is True
    assert target.proposal_id not in {proposal.proposal_id for proposal in filtered}
    rejection_log = (
        tmp_path
        / "spark"
        / "principals"
        / "ken"
        / "memory_review"
        / "rejected_proposals.jsonl"
    )
    assert rejection_log.exists()


def test_personality_memory_context_formats_bounded_rows() -> None:
    context = personality_memory_context(
        [
            {"kind": "voice", "content": "Voice should feel composed."},
            {"kind": "phrase", "content": "Signature phrase: cheers."},
        ]
    )

    assert context == (
        "[WHO YOU'RE TALKING TO]\n"
        "- Voice: Voice should feel composed.\n"
        "- Phrase: Signature phrase: cheers."
    )


@pytest.mark.asyncio
async def test_fetch_personality_memory_uses_bounded_reader() -> None:
    conn = _FakeConn()

    rows = await fetch_personality_memory(conn, "Ken", limit=12)

    assert rows == [{"content": "Voice should feel composed."}]
    assert "public.list_spark_personality_memory" in conn.sql
    assert conn.args == ("ken", 12)


def _write_feedback(root: Path, payload: dict[str, object]) -> None:
    path = root / "spark" / "principals" / "ken" / "feedback" / FEEDBACK_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


class _FakeConn:
    def __init__(self) -> None:
        self.sql = ""
        self.args: tuple[object, ...] = ()

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        self.sql = sql
        self.args = args
        return [{"content": "Voice should feel composed."}]
