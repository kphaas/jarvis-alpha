"""Spark voice feedback records from human-edited drafts.

The feedback file may store Ken-authored draft text and the Spark draft it
replaced. It must never store runtime iMessage context bodies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from brain.services.spark_imessage_drafts import SparkDraftProposal

FEEDBACK_VERSION = "spark-draft-edit-feedback/v0.1"
QUALITY_FEEDBACK_VERSION = "spark-draft-quality-feedback/v0.1"
DEFAULT_FEEDBACK_ROOT = "~/jarvis-personality-feedback"
SPARK_FEEDBACK_ROOT_ENV = "SPARK_VOICE_FEEDBACK_ROOT"
JARVIS_FEEDBACK_ROOT_ENV = "JARVIS_PERSONALITY_FEEDBACK_ROOT"
FEEDBACK_FILENAME = "imessage_draft_edits.jsonl"
MAX_STORED_DRAFT_CHARS = 4000
MAX_KEY_PHRASES = 8
SparkDraftQualityFeedbackLabel = Literal[
    "sounds_like_me",
    "too_robotic",
    "too_formal",
    "too_much_policy",
]


@dataclass(frozen=True, slots=True)
class SparkDraftEditFeedbackResult:
    recorded: bool
    feedback_ref_hash: str | None
    candidate_key_phrases: tuple[str, ...] = ()
    calibration_lessons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SparkDraftQualityFeedbackResult:
    recorded: bool
    feedback_ref_hash: str | None
    feedback_label: SparkDraftQualityFeedbackLabel | None = None


def record_spark_draft_edit_feedback(
    *,
    original_proposal: SparkDraftProposal,
    edited_proposal: SparkDraftProposal,
    vault_root: str | Path | None = None,
    created_at: datetime | None = None,
) -> SparkDraftEditFeedbackResult:
    """Append a sanitized feedback record when a reviewed draft changed."""

    original_text = _clean_text(original_proposal.draft_text)
    edited_text = _clean_text(edited_proposal.draft_text)
    if not edited_text or edited_text == original_text:
        return SparkDraftEditFeedbackResult(recorded=False, feedback_ref_hash=None)

    now = created_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    candidate_key_phrases = extract_candidate_key_phrases(edited_text)
    calibration_lessons = extract_calibration_lessons(
        original_text=original_text,
        edited_text=edited_text,
    )
    record = _feedback_record(
        original_proposal=original_proposal,
        edited_proposal=edited_proposal,
        original_text=original_text,
        edited_text=edited_text,
        candidate_key_phrases=candidate_key_phrases,
        calibration_lessons=calibration_lessons,
        created_at=now,
    )
    feedback_ref_hash = _record_ref_hash(record)
    record["feedback_ref_hash"] = feedback_ref_hash

    path = _feedback_path(vault_root, edited_proposal.principal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        handle.write("\n")

    return SparkDraftEditFeedbackResult(
        recorded=True,
        feedback_ref_hash=feedback_ref_hash,
        candidate_key_phrases=candidate_key_phrases,
        calibration_lessons=calibration_lessons,
    )


def record_spark_draft_quality_feedback(
    *,
    principal_id: str,
    feedback_label: SparkDraftQualityFeedbackLabel,
    draft_version: str,
    approval_ref_hash: str,
    source_reference_hash: str,
    chat_guid_hash: str,
    vault_root: str | Path | None = None,
    created_at: datetime | None = None,
) -> SparkDraftQualityFeedbackResult:
    """Append a label-only quality signal without storing draft or thread text."""

    if feedback_label not in {
        "sounds_like_me",
        "too_robotic",
        "too_formal",
        "too_much_policy",
    }:
        return SparkDraftQualityFeedbackResult(
            recorded=False,
            feedback_ref_hash=None,
        )

    safe_principal = _safe_token(principal_id, fallback="unknown", limit=64)
    if safe_principal == "unknown":
        return SparkDraftQualityFeedbackResult(
            recorded=False,
            feedback_ref_hash=None,
        )

    now = created_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    record = {
        "feedback_version": QUALITY_FEEDBACK_VERSION,
        "created_at": now.astimezone(UTC).isoformat(),
        "principal_id": safe_principal,
        "channel": "imessage",
        "event": "draft_quality_feedback_submitted",
        "feedback_label": feedback_label,
        "draft_version": _safe_token(draft_version, fallback="unknown", limit=80),
        "context_fingerprint": {
            "approval_ref_hash": _safe_hashish(approval_ref_hash),
            "source_reference_hash": _safe_hashish(source_reference_hash),
            "chat_guid_hash": _safe_hashish(chat_guid_hash),
        },
        "guardrails": [
            "no_inbound_runtime_context_stored",
            "label_only_quality_signal",
            "draft_only_no_send",
        ],
    }
    feedback_ref_hash = _record_ref_hash(record)
    record["feedback_ref_hash"] = feedback_ref_hash

    path = _feedback_path(vault_root, safe_principal)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        handle.write("\n")

    return SparkDraftQualityFeedbackResult(
        recorded=True,
        feedback_ref_hash=feedback_ref_hash,
        feedback_label=feedback_label,
    )


def extract_candidate_key_phrases(text: str) -> tuple[str, ...]:
    """Return short phrase seeds for later human review in the Spark UI."""

    clean = _clean_text(text)
    if not clean:
        return ()

    candidates: list[str] = []
    for chunk in re.split(r"[.!?;]|(?:\s+-\s+)|(?:\s+--\s+)|(?:\s+but\s+)", clean):
        phrase = _phrase_candidate(chunk)
        if not phrase or phrase.lower() in {item.lower() for item in candidates}:
            continue
        candidates.append(phrase)
        if len(candidates) >= MAX_KEY_PHRASES:
            break
    return tuple(candidates)


def extract_calibration_lessons(
    *,
    original_text: str,
    edited_text: str,
) -> tuple[str, ...]:
    """Infer reviewable style lessons from a before/after draft edit."""

    original = _clean_text(original_text)
    edited = _clean_text(edited_text)
    if not original or not edited or original == edited:
        return ()

    lessons: list[str] = []
    original_words = _word_count(original)
    edited_words = _word_count(edited)
    original_lower = original.casefold()
    edited_lower = edited.casefold()

    if original_words >= 8 and edited_words <= max(6, int(original_words * 0.75)):
        lessons.append("Prefer shorter text drafts when Spark over-explains.")
    if _has_formal_text_markers(original_lower) and not _has_formal_text_markers(
        edited_lower
    ):
        lessons.append("Avoid formal email-style phrasing in text replies.")
    if _has_contraction(edited) and not _has_contraction(original):
        lessons.append("Prefer natural contractions when they fit the conversation.")
    if re.match(
        r"(?i)^(fair enough|got it|sounds good|makes sense|ok|okay)[,.\s]", edited
    ):
        lessons.append("Lead with a quick acknowledgement before the next action.")
    if edited_words > original_words + 4 and _has_next_action(edited_lower):
        lessons.append("Include the concrete next action when Ken adds one.")

    deduped: list[str] = []
    for lesson in lessons:
        if lesson.casefold() not in {item.casefold() for item in deduped}:
            deduped.append(lesson)
    return tuple(deduped[:5])


def _feedback_record(
    *,
    original_proposal: SparkDraftProposal,
    edited_proposal: SparkDraftProposal,
    original_text: str,
    edited_text: str,
    candidate_key_phrases: tuple[str, ...],
    calibration_lessons: tuple[str, ...],
    created_at: datetime,
) -> dict[str, Any]:
    context = edited_proposal.context
    return {
        "feedback_version": FEEDBACK_VERSION,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "principal_id": edited_proposal.principal_id,
        "channel": "imessage",
        "event": "draft_edit_submitted_for_approval",
        "draft_version": edited_proposal.draft_version,
        "original_draft_engine": original_proposal.draft_engine,
        "edited_draft_engine": edited_proposal.draft_engine,
        "original_draft_text": original_text[:MAX_STORED_DRAFT_CHARS],
        "edited_draft_text": edited_text[:MAX_STORED_DRAFT_CHARS],
        "original_draft_hash": _sha256_text(original_text),
        "edited_draft_hash": _sha256_text(edited_text),
        "candidate_key_phrases": list(candidate_key_phrases),
        "calibration_lessons": list(calibration_lessons),
        "context_fingerprint": {
            "approval_ref_hash": context.approval_ref_hash,
            "source_reference_hash": context.source_reference_hash,
            "chat_guid_hash": context.chat_guid_hash,
            "context_messages_read": len(context.messages),
            "principal_sent_messages": context.principal_sent_messages,
            "runtime_context_messages": context.runtime_context_messages,
        },
        "sensitivity": {
            "detected": list(edited_proposal.detected_sensitivity),
            "blocked": list(edited_proposal.blocked_sensitivity),
        },
        "guardrails": [
            "no_inbound_runtime_context_stored",
            "human_reviewed_edit_only",
            "draft_only_no_send",
        ],
    }


def _feedback_path(vault_root: str | Path | None, principal_id: str) -> Path:
    root = Path(_feedback_root(vault_root)).expanduser()
    safe_principal = re.sub(r"[^A-Za-z0-9_-]+", "-", principal_id).strip("-")
    if not safe_principal:
        safe_principal = "unknown"
    return (
        root / "spark" / "principals" / safe_principal / "feedback" / FEEDBACK_FILENAME
    )


def _feedback_root(vault_root: str | Path | None) -> str:
    if vault_root is not None:
        return str(vault_root)
    return (
        os.environ.get(SPARK_FEEDBACK_ROOT_ENV)
        or os.environ.get(JARVIS_FEEDBACK_ROOT_ENV)
        or DEFAULT_FEEDBACK_ROOT
    )


def _phrase_candidate(value: str) -> str:
    phrase = _clean_text(value).strip(" ,:-")
    if not phrase:
        return ""
    words = phrase.split()
    if len(words) < 2 or len(words) > 10:
        return ""
    lowered = phrase.lower()
    if lowered in {"thank you", "got it", "sounds good"}:
        return ""
    if not any(len(word.strip(" ,.!?")) >= 4 for word in words):
        return ""
    return phrase[:120].strip()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\w']+\b", value))


def _has_formal_text_markers(value: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"thank you for reaching out|"
            r"i hope this message finds you well|"
            r"please let me know|"
            r"best regards|"
            r"sincerely|"
            r"dear\s+\w+"
            r")\b",
            value,
        )
    )


def _has_contraction(value: str) -> bool:
    return bool(re.search(r"\b\w+'(?:m|re|ve|ll|d|s|t)\b", value, re.I))


def _has_next_action(value: str) -> bool:
    return bool(re.search(r"\b(i('| a)?m|i will|i can|let me|we can)\b", value))


def _safe_hashish(value: str) -> str:
    clean = _clean_text(value)
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", clean):
        return clean
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def _safe_token(value: str, *, fallback: str, limit: int) -> str:
    clean = re.sub(r"\s+", "-", value.strip().lower())
    clean = re.sub(r"[^a-z0-9._:@/-]+", "", clean)
    return clean[:limit] or fallback


def _record_ref_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
