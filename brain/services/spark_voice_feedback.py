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
from typing import Any

from brain.services.spark_imessage_drafts import SparkDraftProposal

FEEDBACK_VERSION = "spark-draft-edit-feedback/v0.1"
DEFAULT_FEEDBACK_ROOT = "~/jarvis-personality-feedback"
SPARK_FEEDBACK_ROOT_ENV = "SPARK_VOICE_FEEDBACK_ROOT"
JARVIS_FEEDBACK_ROOT_ENV = "JARVIS_PERSONALITY_FEEDBACK_ROOT"
FEEDBACK_FILENAME = "imessage_draft_edits.jsonl"
MAX_STORED_DRAFT_CHARS = 4000
MAX_KEY_PHRASES = 8


@dataclass(frozen=True, slots=True)
class SparkDraftEditFeedbackResult:
    recorded: bool
    feedback_ref_hash: str | None
    candidate_key_phrases: tuple[str, ...] = ()


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
    record = _feedback_record(
        original_proposal=original_proposal,
        edited_proposal=edited_proposal,
        original_text=original_text,
        edited_text=edited_text,
        candidate_key_phrases=candidate_key_phrases,
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


def _feedback_record(
    *,
    original_proposal: SparkDraftProposal,
    edited_proposal: SparkDraftProposal,
    original_text: str,
    edited_text: str,
    candidate_key_phrases: tuple[str, ...],
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


def _record_ref_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
