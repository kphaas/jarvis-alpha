from __future__ import annotations

import json
from uuid import UUID

import pytest

from brain.services.spark_draft_approvals import (
    SPARK_DRAFT_APPROVAL_ACTION_CLASSES,
    SPARK_DRAFT_APPROVAL_TIER,
    enqueue_spark_draft_approval,
    spark_draft_approval_description,
    spark_draft_parameters_hash,
)
from brain.services.spark_imessage_drafts import (
    SparkDraftContext,
    SparkDraftConversationSummary,
    SparkDraftQualityCheck,
    SparkDraftQualityScorecard,
    SparkDraftProposal,
    SparkDraftSourceReadiness,
    SparkRuntimeMessage,
)


class FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchval(self, query: str, *args: object):
        self.calls.append((query, args))
        return UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.asyncio
async def test_enqueue_spark_draft_approval_stores_only_hash_and_safe_description():
    proposal = _proposal()
    conn = FakeConn()

    queue_id = await enqueue_spark_draft_approval(
        conn,  # type: ignore[arg-type]
        proposal=proposal,
        actor_sub="spark-service",
        actor_type="service",
        nonce="nonce-1",
    )

    assert str(queue_id) == "11111111-1111-4111-8111-111111111111"
    assert len(conn.calls) == 1
    query, args = conn.calls[0]
    assert "enqueue_approval_request" in query
    assert args[0] == list(SPARK_DRAFT_APPROVAL_ACTION_CLASSES)
    assert args[1] == SPARK_DRAFT_APPROVAL_TIER
    assert args[2] == "spark-service"
    assert args[3] == "service"
    assert args[4] == "Spark iMessage draft approval (2 context, 1 sent, 1 runtime)"
    assert args[5] == spark_draft_parameters_hash(proposal)
    assert args[6] == "nonce-1"
    serialized = json.dumps(args).lower()
    assert "private inbound body" not in serialized
    assert "approved-chat-guid" not in serialized
    assert "tell her i am on it" not in serialized


def test_spark_draft_parameters_hash_changes_when_edited_draft_changes():
    proposal = _proposal()
    edited = SparkDraftProposal(
        principal_id=proposal.principal_id,
        draft_text="Edited draft.",
        context=proposal.context,
        conversation_summary=proposal.conversation_summary,
        draft_quality=proposal.draft_quality,
        source_readiness=proposal.source_readiness,
        warnings=proposal.warnings,
    )

    assert spark_draft_parameters_hash(proposal) != spark_draft_parameters_hash(edited)
    assert "private" not in spark_draft_parameters_hash(proposal)
    assert spark_draft_approval_description(proposal) == (
        "Spark iMessage draft approval (2 context, 1 sent, 1 runtime)"
    )


def _proposal() -> SparkDraftProposal:
    return SparkDraftProposal(
        principal_id="ken",
        draft_text="Tell her I am on it.",
        context=SparkDraftContext(
            principal_id="ken",
            approval_ref_hash="approval-hash",
            source_reference_hash="source-hash",
            chat_guid_hash="chat-hash",
            messages=(
                SparkRuntimeMessage(
                    message_ref_hash="msg-1",
                    is_from_me=False,
                    body_text="private inbound body",
                ),
                SparkRuntimeMessage(
                    message_ref_hash="msg-2",
                    is_from_me=True,
                    body_text="ken sent private body",
                ),
            ),
        ),
        conversation_summary=SparkDraftConversationSummary(
            channel="iMessage",
            voice_principal_label="Ken",
            reply_target_label="Sweta",
            reply_target_confidence="approved_source_label",
        ),
        draft_quality=SparkDraftQualityScorecard(
            score=100,
            verdict="strong",
            checks=(
                SparkDraftQualityCheck(
                    key="length",
                    label="Short enough",
                    passed=True,
                    detail="5 words; Spark should stay short to medium.",
                ),
            ),
        ),
        source_readiness=(
            SparkDraftSourceReadiness(
                source="imessage",
                channel="Text",
                status="live_runtime_context",
                detail="Approved iMessage thread is feeding this draft at runtime.",
            ),
        ),
        warnings=("draft_only_no_send",),
    )
