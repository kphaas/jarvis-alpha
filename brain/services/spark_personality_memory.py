"""Spark-reviewed personality memory service.

This module keeps persona memory separate from semantic memory. Spark may
propose bounded identity/voice facts, but only the explicit approval route
commits them through the SECDEF writer.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import asyncpg

from brain.services.spark_persona_guardrails import (
    SparkGuardrailState,
    load_spark_guardrails,
)
from brain.services.spark_voice_feedback import (
    DEFAULT_FEEDBACK_ROOT,
    FEEDBACK_FILENAME,
    JARVIS_FEEDBACK_ROOT_ENV,
    SPARK_FEEDBACK_ROOT_ENV,
)

PersonalityMemoryKind = Literal[
    "voice",
    "avoid",
    "phrase",
    "boundary",
    "relationship",
    "value",
    "style",
    "preference",
]
PersonalityMemorySource = Literal[
    "spark_approved",
    "spark_feedback",
    "spark_vault",
    "buddy_proposal",
]

CONTEXT_MAX_LINES = 18
SAFE_PRINCIPAL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
BLOCKED_CONTENT = re.compile(
    r"\b(password|token|secret|private key|raw thread|message body|phone number)\b",
    re.IGNORECASE,
)
PROPOSAL_ID = re.compile(r"^[a-f0-9]{8,64}$")
REJECTION_FILENAME = "rejected_proposals.jsonl"


@dataclass(frozen=True, slots=True)
class SparkPersonalityMemoryProposal:
    proposal_id: str
    principal_id: str
    kind: PersonalityMemoryKind
    content: str
    source: PersonalityMemorySource
    reason: str
    confidence: float
    evidence_ref_hash: str | None = None


def safe_principal_id(value: str | None) -> str | None:
    clean = (value or "").strip().lower()
    if not clean or clean in {"anon", "unknown", "system"}:
        return None
    if not SAFE_PRINCIPAL.fullmatch(clean):
        return None
    return clean


async def fetch_personality_memory(
    conn: asyncpg.Connection,
    principal_id: str | None,
    *,
    limit: int = 24,
) -> list[dict[str, object]]:
    principal = safe_principal_id(principal_id)
    if principal is None:
        return []
    rows = await conn.fetch(
        """
        SELECT *
        FROM public.list_spark_personality_memory($1, $2)
        """,
        principal,
        limit,
    )
    return [dict(row) for row in rows]


def personality_memory_context(
    rows: list[dict[str, object]],
    *,
    max_lines: int = CONTEXT_MAX_LINES,
) -> str:
    lines: list[str] = []
    for row in rows:
        kind = str(row.get("kind") or "memory").replace("_", " ")
        content = _safe_content(str(row.get("content") or ""))
        if content:
            lines.append(f"{kind.title()}: {content}")
        if len(lines) >= max_lines:
            break
    if not lines:
        return ""
    return "[WHO YOU'RE TALKING TO]\n" + "\n".join(f"- {line}" for line in lines)


async def save_personality_memory(
    conn: asyncpg.Connection,
    *,
    principal_id: str,
    kind: str,
    content: str,
    source: str,
    evidence_ref_hash: str | None,
    approved_by: str,
    importance_score: float,
) -> dict[str, object]:
    payload = await conn.fetchval(
        """
        SELECT public.save_spark_personality_memory(
            $1, $2, $3, $4, $5, $6, $7
        )
        """,
        principal_id,
        kind,
        content,
        source,
        evidence_ref_hash,
        approved_by,
        importance_score,
    )
    if isinstance(payload, str):
        return dict(json.loads(payload))
    return dict(payload)


async def archive_personality_memory(
    conn: asyncpg.Connection,
    *,
    principal_id: str,
    memory_id: str,
    archived_by: str,
) -> dict[str, object]:
    payload = await conn.fetchval(
        """
        SELECT public.archive_spark_personality_memory(
            $1, $2::uuid, $3
        )
        """,
        principal_id,
        memory_id,
        archived_by,
    )
    if isinstance(payload, str):
        return dict(json.loads(payload))
    return dict(payload)


def reject_personality_memory_proposal(
    *,
    principal_id: str,
    proposal_id: str,
    rejected_by: str,
    feedback_root: str | Path | None = None,
) -> dict[str, object]:
    principal = safe_principal_id(principal_id)
    clean_proposal_id = (proposal_id or "").strip().lower()
    clean_rejected_by = _safe_reviewer(rejected_by)
    if principal is None:
        return {"rejected": False, "reason": "invalid_principal"}
    if not PROPOSAL_ID.fullmatch(clean_proposal_id):
        return {"rejected": False, "reason": "invalid_proposal"}
    if not clean_rejected_by:
        return {"rejected": False, "reason": "invalid_rejected_by"}

    rejected = _rejected_proposal_ids(
        principal_id=principal,
        feedback_root=feedback_root,
    )
    if clean_proposal_id in rejected:
        return {
            "rejected": True,
            "proposal_id": clean_proposal_id,
            "principal_id": principal,
            "already_rejected": True,
        }

    from datetime import UTC, datetime

    record = {
        "event": "spark_personality_memory_proposal_rejected",
        "created_at": datetime.now(UTC).isoformat(),
        "principal_id": principal,
        "proposal_id": clean_proposal_id,
        "rejected_by": clean_rejected_by,
    }
    path = _rejection_file_path(principal_id=principal, feedback_root=feedback_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
    return {
        "rejected": True,
        "proposal_id": clean_proposal_id,
        "principal_id": principal,
        "already_rejected": False,
    }


def build_personality_memory_proposals(
    *,
    principal_id: str = "ken",
    guardrails: SparkGuardrailState | None = None,
    feedback_root: str | Path | None = None,
    existing_rows: list[dict[str, object]] | None = None,
) -> tuple[SparkPersonalityMemoryProposal, ...]:
    principal = safe_principal_id(principal_id) or "ken"
    state = guardrails or load_spark_guardrails()
    existing = {
        (
            str(row.get("kind") or "").lower(),
            str(row.get("content") or "").strip().casefold(),
        )
        for row in existing_rows or []
    }
    proposals: list[SparkPersonalityMemoryProposal] = []

    for marker in state.calibration.target_voice:
        _append_proposal(
            proposals,
            principal_id=principal,
            kind="voice",
            content=f"Voice should feel {marker}.",
            source="spark_vault",
            reason="approved guardrail target voice",
            confidence=0.9,
            existing=existing,
        )
    for marker in state.calibration.avoid_voice:
        _append_proposal(
            proposals,
            principal_id=principal,
            kind="avoid",
            content=f"Avoid sounding {marker}.",
            source="spark_vault",
            reason="approved guardrail avoid voice",
            confidence=0.9,
            existing=existing,
        )
    for phrase in state.calibration.signature_phrases:
        _append_proposal(
            proposals,
            principal_id=principal,
            kind="phrase",
            content=f"Signature phrase: {phrase}.",
            source="spark_vault",
            reason="approved guardrail signature phrase",
            confidence=0.85,
            existing=existing,
        )
    for topic in state.protected_topics:
        _append_proposal(
            proposals,
            principal_id=principal,
            kind="boundary",
            content=f"{topic} topics require Spark review before action.",
            source="spark_vault",
            reason="approved protected topic",
            confidence=0.95,
            existing=existing,
        )
    for relationship in state.protected_relationships:
        content = (
            f"{relationship.label}: {relationship.relationship}; "
            f"sensitivity {relationship.sensitivity}; "
            f"default {relationship.default_mode}; "
            f"approval required {relationship.approval_required}."
        )
        _append_proposal(
            proposals,
            principal_id=principal,
            kind="relationship",
            content=content,
            source="spark_vault",
            reason="approved protected relationship",
            confidence=0.95,
            existing=existing,
        )

    for phrase, evidence_hash in _candidate_key_phrases(
        principal_id=principal,
        feedback_root=feedback_root,
    ):
        _append_proposal(
            proposals,
            principal_id=principal,
            kind="phrase",
            content=f"Candidate phrase from reviewed draft edit: {phrase}.",
            source="spark_feedback",
            reason="human-edited Spark draft feedback",
            confidence=0.65,
            evidence_ref_hash=evidence_hash,
            existing=existing,
        )

    rejected = _rejected_proposal_ids(
        principal_id=principal,
        feedback_root=feedback_root,
    )
    if rejected:
        proposals = [
            proposal for proposal in proposals if proposal.proposal_id not in rejected
        ]

    return tuple(proposals[:40])


def collect_spark_personality_memory_status(
    *,
    principal_id: str = "ken",
    existing_rows: list[dict[str, object]] | None = None,
    feedback_root: str | Path | None = None,
) -> dict[str, object]:
    proposals = build_personality_memory_proposals(
        principal_id=principal_id,
        feedback_root=feedback_root,
        existing_rows=existing_rows,
    )
    return {
        "principal_id": safe_principal_id(principal_id) or "unknown",
        "status": "ok",
        "proposal_count": len(proposals),
        "feedback_phrase_count": sum(
            1 for proposal in proposals if proposal.source == "spark_feedback"
        ),
        "active_count": len(existing_rows or []),
    }


def _append_proposal(
    proposals: list[SparkPersonalityMemoryProposal],
    *,
    principal_id: str,
    kind: PersonalityMemoryKind,
    content: str,
    source: PersonalityMemorySource,
    reason: str,
    confidence: float,
    existing: set[tuple[str, str]],
    evidence_ref_hash: str | None = None,
) -> None:
    clean = _safe_content(content)
    if not clean or (kind, clean.casefold()) in existing:
        return
    seen = {(proposal.kind, proposal.content.casefold()) for proposal in proposals}
    if (kind, clean.casefold()) in seen:
        return
    proposals.append(
        SparkPersonalityMemoryProposal(
            proposal_id=_proposal_id(principal_id, kind, clean, source),
            principal_id=principal_id,
            kind=kind,
            content=clean,
            source=source,
            reason=reason,
            confidence=confidence,
            evidence_ref_hash=evidence_ref_hash,
        )
    )


def _candidate_key_phrases(
    *,
    principal_id: str,
    feedback_root: str | Path | None,
) -> list[tuple[str, str]]:
    path = _feedback_file_path(principal_id=principal_id, feedback_root=feedback_root)
    phrases: list[tuple[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        feedback_hash = str(row.get("feedback_ref_hash") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", feedback_hash):
            feedback_hash = hashlib.sha256(line.encode("utf-8")).hexdigest()
        for phrase in row.get("candidate_key_phrases") or []:
            clean = _safe_content(str(phrase))
            if clean:
                phrases.append((clean, feedback_hash))
    return phrases


def _feedback_file_path(
    *,
    principal_id: str,
    feedback_root: str | Path | None,
) -> Path:
    root = _feedback_root(feedback_root)
    return (
        root.expanduser()
        / "spark"
        / "principals"
        / principal_id
        / "feedback"
        / FEEDBACK_FILENAME
    )


def _rejection_file_path(
    *,
    principal_id: str,
    feedback_root: str | Path | None,
) -> Path:
    root = _feedback_root(feedback_root)
    return (
        root.expanduser()
        / "spark"
        / "principals"
        / principal_id
        / "memory_review"
        / REJECTION_FILENAME
    )


def _feedback_root(feedback_root: str | Path | None) -> Path:
    if feedback_root is not None:
        return Path(feedback_root)

    import os

    return Path(
        os.environ.get(SPARK_FEEDBACK_ROOT_ENV)
        or os.environ.get(JARVIS_FEEDBACK_ROOT_ENV)
        or DEFAULT_FEEDBACK_ROOT
    )


def _rejected_proposal_ids(
    *,
    principal_id: str,
    feedback_root: str | Path | None,
) -> set[str]:
    path = _rejection_file_path(
        principal_id=principal_id,
        feedback_root=feedback_root,
    )
    rejected: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return rejected
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        proposal_id = str(row.get("proposal_id") or "").strip().lower()
        if PROPOSAL_ID.fullmatch(proposal_id):
            rejected.add(proposal_id)
    return rejected


def _safe_content(value: str) -> str:
    clean = re.sub(r"\s+", " ", value).strip().strip("\"'")
    if not clean or BLOCKED_CONTENT.search(clean):
        return ""
    if len(clean) > 500:
        clean = clean[:497].rstrip() + "..."
    return clean


def _safe_reviewer(value: str) -> str:
    clean = re.sub(r"\s+", "-", value.strip().lower())
    clean = re.sub(r"[^a-z0-9@._-]+", "", clean)
    return clean[:128]


def _proposal_id(
    principal_id: str,
    kind: str,
    content: str,
    source: str,
) -> str:
    payload = f"{principal_id}|{kind}|{source}|{content}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]
