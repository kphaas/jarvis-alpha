from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from brain.services.spark_imessage_drafts import (
    SparkDraftContext,
    SparkDraftConversationSummary,
    SparkDraftQualityCheck,
    SparkDraftQualityScorecard,
    SparkDraftProposal,
    SparkDraftSourceReadiness,
    SparkRuntimeMessage,
    apply_draft_text_override,
)
from brain.services.spark_voice_feedback import (
    extract_calibration_lessons,
    extract_candidate_key_phrases,
    load_recent_feedback_lessons,
    record_spark_draft_edit_feedback,
    record_spark_draft_quality_feedback,
)


def test_draft_edit_feedback_records_only_drafts_and_safe_context_hashes(
    tmp_path: Path,
) -> None:
    original = _proposal("That is the plan then. We can talk through it.")
    edited = apply_draft_text_override(
        original,
        "Perfect. Let's make this one count first.",
    )

    result = record_spark_draft_edit_feedback(
        original_proposal=original,
        edited_proposal=edited,
        vault_root=tmp_path,
        created_at=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
    )

    assert result.recorded is True
    assert result.feedback_ref_hash
    assert "Let's make this one count first" in result.candidate_key_phrases
    assert result.calibration_lessons == (
        "Prefer shorter text drafts when Spark over-explains.",
        "Prefer natural contractions when they fit the conversation.",
    )

    feedback_path = (
        tmp_path
        / "spark"
        / "principals"
        / "ken"
        / "feedback"
        / "imessage_draft_edits.jsonl"
    )
    rows = [
        json.loads(line)
        for line in feedback_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["feedback_version"] == "spark-draft-edit-feedback/v0.1"
    assert (
        row["original_draft_text"] == "That is the plan then. We can talk through it."
    )
    assert row["edited_draft_text"] == "Perfect. Let's make this one count first."
    assert row["edited_draft_engine"] == "human_override"
    assert row["calibration_lessons"] == [
        "Prefer shorter text drafts when Spark over-explains.",
        "Prefer natural contractions when they fit the conversation.",
    ]
    assert row["context_fingerprint"] == {
        "approval_ref_hash": "approval-hash",
        "source_reference_hash": "source-hash",
        "chat_guid_hash": "chat-hash",
        "context_messages_read": 2,
        "principal_sent_messages": 1,
        "runtime_context_messages": 1,
    }
    serialized = json.dumps(row).lower()
    assert "private inbound body" not in serialized
    assert "ken sent private body" not in serialized


def test_draft_edit_feedback_skips_unchanged_text(tmp_path: Path) -> None:
    original = _proposal("Fair enough, I am on it.")
    edited = apply_draft_text_override(original, "Fair enough, I am on it.")

    result = record_spark_draft_edit_feedback(
        original_proposal=original,
        edited_proposal=edited,
        vault_root=tmp_path,
    )

    assert result.recorded is False
    assert result.feedback_ref_hash is None
    assert not (tmp_path / "spark").exists()


def test_draft_quality_feedback_records_label_only(tmp_path: Path) -> None:
    result = record_spark_draft_quality_feedback(
        principal_id="ken",
        feedback_label="too_wordy",
        draft_version="spark-imessage-draft/v0",
        approval_ref_hash="approval-hash",
        source_reference_hash="source-hash",
        chat_guid_hash="chat-hash",
        vault_root=tmp_path,
        created_at=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
    )

    assert result.recorded is True
    assert result.feedback_ref_hash
    feedback_path = (
        tmp_path
        / "spark"
        / "principals"
        / "ken"
        / "feedback"
        / "imessage_draft_edits.jsonl"
    )
    row = json.loads(feedback_path.read_text(encoding="utf-8").strip())
    assert row["feedback_version"] == "spark-draft-quality-feedback/v0.1"
    assert row["feedback_label"] == "too_wordy"
    serialized = json.dumps(row).lower()
    assert "draft_text" not in serialized
    assert "private inbound body" not in serialized
    assert "ken sent private body" not in serialized


def test_draft_quality_feedback_accepts_out_of_context(tmp_path: Path) -> None:
    result = record_spark_draft_quality_feedback(
        principal_id="ken",
        feedback_label="out_of_context",
        draft_version="spark-imessage-draft/v0",
        approval_ref_hash="approval-hash",
        source_reference_hash="source-hash",
        chat_guid_hash="chat-hash",
        vault_root=tmp_path,
        created_at=datetime(2026, 6, 15, 9, 5, tzinfo=UTC),
    )

    assert result.recorded is True
    assert result.feedback_ref_hash
    feedback_path = (
        tmp_path
        / "spark"
        / "principals"
        / "ken"
        / "feedback"
        / "imessage_draft_edits.jsonl"
    )
    row = json.loads(feedback_path.read_text(encoding="utf-8").strip())
    assert row["feedback_label"] == "out_of_context"


def test_draft_quality_feedback_accepts_voice_rewrite(tmp_path: Path) -> None:
    result = record_spark_draft_quality_feedback(
        principal_id="ken",
        feedback_label="voice_rewrite",
        draft_version="spark-imessage-draft/v0",
        approval_ref_hash="approval-hash",
        source_reference_hash="source-hash",
        chat_guid_hash="chat-hash",
        vault_root=tmp_path,
        created_at=datetime(2026, 6, 15, 9, 7, tzinfo=UTC),
    )

    assert result.recorded is True
    feedback_path = (
        tmp_path
        / "spark"
        / "principals"
        / "ken"
        / "feedback"
        / "imessage_draft_edits.jsonl"
    )
    row = json.loads(feedback_path.read_text(encoding="utf-8").strip())
    assert row["feedback_label"] == "voice_rewrite"


def test_feedback_default_root_is_not_personality_git_checkout() -> None:
    from brain.services import spark_voice_feedback as feedback

    assert feedback._feedback_root(None) == "~/jarvis-personality-feedback"


def test_candidate_key_phrases_are_short_review_seeds() -> None:
    assert extract_candidate_key_phrases(
        "Fair enough. Let's make this one count first. Got it."
    ) == ("Fair enough", "Let's make this one count first")


def test_calibration_lessons_capture_reviewable_edit_patterns() -> None:
    lessons = extract_calibration_lessons(
        original_text=(
            "Thank you for reaching out. Please let me know if you need anything "
            "else from me on this."
        ),
        edited_text="Got it, I'm on it.",
    )

    assert lessons == (
        "Prefer shorter text drafts when Spark over-explains.",
        "Avoid formal email-style phrasing in text replies.",
        "Prefer natural contractions when they fit the conversation.",
        "Lead with a quick acknowledgement before the next action.",
    )


def test_recent_feedback_lessons_merge_quality_and_edit_signals(tmp_path: Path) -> None:
    original = _proposal(
        "Thank you for reaching out. Please let me know if you need anything else."
    )
    edited = apply_draft_text_override(original, "Got it, I'm on it.")
    record_spark_draft_edit_feedback(
        original_proposal=original,
        edited_proposal=edited,
        vault_root=tmp_path,
        created_at=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
    )
    record_spark_draft_quality_feedback(
        principal_id="ken",
        feedback_label="out_of_context",
        draft_version="spark-imessage-draft/v0",
        approval_ref_hash="approval-hash",
        source_reference_hash="source-hash",
        chat_guid_hash="chat-hash",
        vault_root=tmp_path,
        created_at=datetime(2026, 6, 15, 9, 5, tzinfo=UTC),
    )

    lessons = load_recent_feedback_lessons(
        principal_id="ken",
        vault_root=tmp_path,
    )

    assert (
        lessons[0]
        == "Answer the latest inbound text before adding a new topic or explanation."
    )
    assert (
        "Reuse the concrete ask or noun from the latest inbound text before pivoting."
        in lessons
    )
    assert "Prefer shorter text drafts when Spark over-explains." in lessons


def test_recent_feedback_lessons_prioritize_voice_rewrite(tmp_path: Path) -> None:
    record_spark_draft_quality_feedback(
        principal_id="ken",
        feedback_label="voice_rewrite",
        draft_version="spark-imessage-draft/v0",
        approval_ref_hash="approval-hash",
        source_reference_hash="source-hash",
        chat_guid_hash="chat-hash",
        vault_root=tmp_path,
        created_at=datetime(2026, 6, 15, 9, 7, tzinfo=UTC),
    )

    lessons = load_recent_feedback_lessons(
        principal_id="ken",
        vault_root=tmp_path,
    )

    assert (
        lessons[0]
        == "Treat Ken's edited draft text as the strongest available voice signal for the next reply."
    )
    assert (
        "Prefer Ken's exact rewrite pattern over generic polishing when the draft was manually corrected."
        in lessons
    )


def test_recent_feedback_lessons_add_tighter_word_count_guidance(
    tmp_path: Path,
) -> None:
    record_spark_draft_quality_feedback(
        principal_id="ken",
        feedback_label="too_wordy",
        draft_version="spark-imessage-draft/v0",
        approval_ref_hash="approval-hash",
        source_reference_hash="source-hash",
        chat_guid_hash="chat-hash",
        vault_root=tmp_path,
        created_at=datetime(2026, 6, 15, 9, 10, tzinfo=UTC),
    )

    lessons = load_recent_feedback_lessons(
        principal_id="ken",
        vault_root=tmp_path,
    )

    assert "Use fewer words and stop after the useful answer." in lessons
    assert (
        "Default to one or two short text-message sentences unless the thread truly needs more."
        in lessons
    )


def _proposal(draft_text: str) -> SparkDraftProposal:
    return SparkDraftProposal(
        principal_id="ken",
        draft_text=draft_text,
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
        draft_engine="gateway_llm",
    )
