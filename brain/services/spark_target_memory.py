"""Reviewed Spark target-memory service.

This lane stores selected-recipient facts, preferences, and open loops
separately from principal personality memory. It never persists raw message
bodies. Review proposals store only operator-authored summary text plus
evidence hashes tied to the selected thread preview.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import asyncpg

TargetMemoryKind = Literal["profile_fact", "preference", "open_loop"]
TargetMemorySource = Literal["thread_mark"]
DEFAULT_FEEDBACK_ROOT = "~/jarvis-personality-feedback"
SPARK_FEEDBACK_ROOT_ENV = "SPARK_VOICE_FEEDBACK_ROOT"
JARVIS_FEEDBACK_ROOT_ENV = "JARVIS_PERSONALITY_FEEDBACK_ROOT"

SAFE_PRINCIPAL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
HEX_HASH = re.compile(r"^[a-f0-9]{64}$")
PROPOSAL_ID = re.compile(r"^[a-f0-9]{8,64}$")
BLOCKED_CONTENT = re.compile(
    r"\b(password|token|secret|private key|raw thread|message body|phone number)\b",
    re.IGNORECASE,
)
PROPOSAL_FILENAME = "target_memory_proposals.jsonl"
REJECTION_FILENAME = "rejected_target_memory_proposals.jsonl"
TARGET_MEMORY_MAX_PROMPT_ITEMS = 8


@dataclass(frozen=True, slots=True)
class SparkTargetMemoryProposal:
    proposal_id: str
    principal_id: str
    approval_id: str
    target_ref_hash: str
    target_label: str
    kind: TargetMemoryKind
    content: str
    source: TargetMemorySource
    reason: str
    confidence: float
    evidence_ref_hash: str | None = None
    approval_ref_hash: str | None = None
    source_reference_hash: str | None = None
    chat_guid_hash: str | None = None


@dataclass(frozen=True, slots=True)
class SparkTargetMemoryPromptItem:
    kind: str
    content: str
    source: str
    reason: str
    evidence_ref_hash: str | None = None


def safe_principal_id(value: str | None) -> str | None:
    clean = (value or "").strip().lower()
    if not clean or clean in {"anon", "unknown", "system"}:
        return None
    if not SAFE_PRINCIPAL.fullmatch(clean):
        return None
    return clean


async def fetch_target_memory(
    conn: asyncpg.Connection,
    principal_id: str | None,
    target_ref_hash: str | None,
    *,
    limit: int = 12,
) -> list[dict[str, object]]:
    principal = safe_principal_id(principal_id)
    target_hash = _safe_hash(target_ref_hash)
    if principal is None or target_hash is None:
        return []
    rows = await conn.fetch(
        """
        SELECT *
        FROM public.list_spark_target_memory($1, $2, $3)
        """,
        principal,
        target_hash,
        limit,
    )
    return [dict(row) for row in rows]


async def save_target_memory(
    conn: asyncpg.Connection,
    *,
    principal_id: str,
    target_ref_hash: str,
    target_label: str,
    kind: str,
    content: str,
    source: str,
    evidence_ref_hash: str | None,
    approved_by: str,
    importance_score: float,
) -> dict[str, object]:
    payload = await conn.fetchval(
        """
        SELECT public.save_spark_target_memory(
            $1, $2, $3, $4, $5, $6, $7, $8, $9
        )
        """,
        principal_id,
        target_ref_hash,
        target_label,
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


async def archive_target_memory(
    conn: asyncpg.Connection,
    *,
    principal_id: str,
    memory_id: str,
    archived_by: str,
) -> dict[str, object]:
    payload = await conn.fetchval(
        """
        SELECT public.archive_spark_target_memory(
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


def list_target_memory_proposals(
    *,
    principal_id: str,
    target_ref_hash: str,
    existing_rows: list[dict[str, object]] | None = None,
    feedback_root: str | Path | None = None,
) -> tuple[SparkTargetMemoryProposal, ...]:
    principal = safe_principal_id(principal_id) or "ken"
    target_hash = _safe_hash(target_ref_hash)
    if target_hash is None:
        return ()
    active = {
        (
            str(row.get("kind") or "").lower(),
            str(row.get("content") or "").strip().casefold(),
        )
        for row in existing_rows or []
    }
    rejected = _rejected_proposal_ids(
        principal_id=principal,
        target_ref_hash=target_hash,
        feedback_root=feedback_root,
    )
    proposals: list[SparkTargetMemoryProposal] = []
    seen: set[str] = set()
    for row in reversed(
        _proposal_rows(
            principal_id=principal,
            target_ref_hash=target_hash,
            feedback_root=feedback_root,
        )
    ):
        proposal = _proposal_from_row(row)
        if proposal is None:
            continue
        if proposal.proposal_id in rejected or proposal.proposal_id in seen:
            continue
        if (proposal.kind, proposal.content.casefold()) in active:
            continue
        seen.add(proposal.proposal_id)
        proposals.append(proposal)
        if len(proposals) >= 24:
            break
    return tuple(proposals)


def propose_target_memory_from_note(
    *,
    principal_id: str,
    approval_id: str,
    target_ref_hash: str,
    target_label: str,
    kind: TargetMemoryKind,
    note: str,
    approval_ref_hash: str,
    source_reference_hash: str,
    chat_guid_hash: str,
    feedback_root: str | Path | None = None,
) -> SparkTargetMemoryProposal | None:
    principal = safe_principal_id(principal_id) or "ken"
    target_hash = _safe_hash(target_ref_hash)
    approval_hash = _safe_hash(approval_ref_hash)
    source_hash = _safe_hash(source_reference_hash)
    chat_hash = _safe_hash(chat_guid_hash)
    label = _safe_target_label(target_label)
    content = _normalize_note_content(note)
    if (
        target_hash is None
        or approval_hash is None
        or source_hash is None
        or chat_hash is None
        or label is None
        or content is None
    ):
        return None

    evidence_ref_hash = hashlib.sha256(
        f"{approval_hash}|{source_hash}|{chat_hash}".encode("utf-8")
    ).hexdigest()
    proposal = SparkTargetMemoryProposal(
        proposal_id=_proposal_id(principal, target_hash, kind, content, "thread_mark"),
        principal_id=principal,
        approval_id=approval_id.strip(),
        target_ref_hash=target_hash,
        target_label=label,
        kind=kind,
        content=content,
        source="thread_mark",
        reason=_proposal_reason(kind),
        confidence=_proposal_confidence(kind),
        evidence_ref_hash=evidence_ref_hash,
        approval_ref_hash=approval_hash,
        source_reference_hash=source_hash,
        chat_guid_hash=chat_hash,
    )
    _append_proposal_row(proposal, feedback_root=feedback_root)
    return proposal


def reject_target_memory_proposal(
    *,
    principal_id: str,
    target_ref_hash: str,
    proposal_id: str,
    rejected_by: str,
    feedback_root: str | Path | None = None,
) -> dict[str, object]:
    principal = safe_principal_id(principal_id)
    target_hash = _safe_hash(target_ref_hash)
    clean_proposal_id = (proposal_id or "").strip().lower()
    clean_rejected_by = _safe_reviewer(rejected_by)
    if principal is None:
        return {"rejected": False, "reason": "invalid_principal"}
    if target_hash is None:
        return {"rejected": False, "reason": "invalid_target_ref_hash"}
    if not PROPOSAL_ID.fullmatch(clean_proposal_id):
        return {"rejected": False, "reason": "invalid_proposal"}
    if not clean_rejected_by:
        return {"rejected": False, "reason": "invalid_rejected_by"}

    rejected = _rejected_proposal_ids(
        principal_id=principal,
        target_ref_hash=target_hash,
        feedback_root=feedback_root,
    )
    if clean_proposal_id in rejected:
        return {
            "rejected": True,
            "proposal_id": clean_proposal_id,
            "principal_id": principal,
            "target_ref_hash": target_hash,
            "already_rejected": True,
        }

    from datetime import UTC, datetime

    record = {
        "event": "spark_target_memory_proposal_rejected",
        "created_at": datetime.now(UTC).isoformat(),
        "principal_id": principal,
        "target_ref_hash": target_hash,
        "proposal_id": clean_proposal_id,
        "rejected_by": clean_rejected_by,
    }
    path = _rejection_file_path(
        principal_id=principal,
        target_ref_hash=target_hash,
        feedback_root=feedback_root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
    return {
        "rejected": True,
        "proposal_id": clean_proposal_id,
        "principal_id": principal,
        "target_ref_hash": target_hash,
        "already_rejected": False,
    }


def target_memory_prompt_items(
    rows: list[dict[str, object]],
    *,
    max_items: int = TARGET_MEMORY_MAX_PROMPT_ITEMS,
) -> list[SparkTargetMemoryPromptItem]:
    priority = {"open_loop": 0, "preference": 1, "profile_fact": 2}
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            priority.get(str(row.get("kind") or "").strip().lower(), 9),
            -float(row.get("importance_score") or 0),
        ),
    )
    items: list[SparkTargetMemoryPromptItem] = []
    seen: set[tuple[str, str]] = set()
    for row in ordered_rows:
        kind = str(row.get("kind") or "").strip().lower()
        if kind not in priority:
            continue
        content = _normalize_note_content(str(row.get("content") or ""))
        if content is None:
            continue
        key = (kind, content.casefold())
        if key in seen:
            continue
        seen.add(key)
        evidence_ref_hash = row.get("evidence_ref_hash")
        items.append(
            SparkTargetMemoryPromptItem(
                kind=kind,
                content=content[:240],
                source=str(row.get("source") or "unknown"),
                reason=_prompt_reason(kind),
                evidence_ref_hash=(
                    str(evidence_ref_hash).strip() if evidence_ref_hash else None
                ),
            )
        )
        if len(items) >= max_items:
            break
    return items


def target_memory_prompt_context(rows: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for item in target_memory_prompt_items(rows):
        lines.append(f"- {item.kind.replace('_', ' ').title()}: {item.content}")
    return "\n".join(lines)


def _append_proposal_row(
    proposal: SparkTargetMemoryProposal,
    *,
    feedback_root: str | Path | None,
) -> None:
    from datetime import UTC, datetime

    path = _proposal_file_path(
        principal_id=proposal.principal_id,
        target_ref_hash=proposal.target_ref_hash,
        feedback_root=feedback_root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": "spark_target_memory_proposed",
        "created_at": datetime.now(UTC).isoformat(),
        "proposal_id": proposal.proposal_id,
        "principal_id": proposal.principal_id,
        "approval_id": proposal.approval_id,
        "target_ref_hash": proposal.target_ref_hash,
        "target_label": proposal.target_label,
        "kind": proposal.kind,
        "content": proposal.content,
        "source": proposal.source,
        "reason": proposal.reason,
        "confidence": proposal.confidence,
        "evidence_ref_hash": proposal.evidence_ref_hash,
        "approval_ref_hash": proposal.approval_ref_hash,
        "source_reference_hash": proposal.source_reference_hash,
        "chat_guid_hash": proposal.chat_guid_hash,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        handle.write("\n")


def _proposal_rows(
    *,
    principal_id: str,
    target_ref_hash: str,
    feedback_root: str | Path | None,
) -> list[dict[str, object]]:
    path = _proposal_file_path(
        principal_id=principal_id,
        target_ref_hash=target_ref_hash,
        feedback_root=feedback_root,
    )
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    rows: list[dict[str, object]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _proposal_from_row(row: dict[str, object]) -> SparkTargetMemoryProposal | None:
    proposal_id = str(row.get("proposal_id") or "").strip().lower()
    principal_id = safe_principal_id(str(row.get("principal_id") or ""))
    approval_id = str(row.get("approval_id") or "").strip()
    target_ref_hash = _safe_hash(str(row.get("target_ref_hash") or ""))
    target_label = _safe_target_label(str(row.get("target_label") or ""))
    kind = str(row.get("kind") or "").strip().lower()
    content = _normalize_note_content(str(row.get("content") or ""))
    source = str(row.get("source") or "").strip().lower()
    reason = " ".join(str(row.get("reason") or "").split()).strip()
    if (
        not PROPOSAL_ID.fullmatch(proposal_id)
        or principal_id is None
        or not approval_id
        or target_ref_hash is None
        or target_label is None
        or kind not in {"profile_fact", "preference", "open_loop"}
        or content is None
        or source != "thread_mark"
    ):
        return None
    confidence = float(row.get("confidence") or 0.7)
    return SparkTargetMemoryProposal(
        proposal_id=proposal_id,
        principal_id=principal_id,
        approval_id=approval_id,
        target_ref_hash=target_ref_hash,
        target_label=target_label,
        kind=kind,
        content=content,
        source="thread_mark",
        reason=reason or _proposal_reason(kind),
        confidence=max(0.0, min(confidence, 1.0)),
        evidence_ref_hash=_safe_hash(str(row.get("evidence_ref_hash") or "")),
        approval_ref_hash=_safe_hash(str(row.get("approval_ref_hash") or "")),
        source_reference_hash=_safe_hash(str(row.get("source_reference_hash") or "")),
        chat_guid_hash=_safe_hash(str(row.get("chat_guid_hash") or "")),
    )


def _proposal_file_path(
    *,
    principal_id: str,
    target_ref_hash: str,
    feedback_root: str | Path | None,
) -> Path:
    root = _feedback_root(feedback_root)
    return (
        root.expanduser()
        / "spark"
        / "principals"
        / principal_id
        / "targets"
        / target_ref_hash
        / "memory_review"
        / PROPOSAL_FILENAME
    )


def _rejection_file_path(
    *,
    principal_id: str,
    target_ref_hash: str,
    feedback_root: str | Path | None,
) -> Path:
    root = _feedback_root(feedback_root)
    return (
        root.expanduser()
        / "spark"
        / "principals"
        / principal_id
        / "targets"
        / target_ref_hash
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
    target_ref_hash: str,
    feedback_root: str | Path | None,
) -> set[str]:
    path = _rejection_file_path(
        principal_id=principal_id,
        target_ref_hash=target_ref_hash,
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


def _proposal_id(
    principal_id: str,
    target_ref_hash: str,
    kind: str,
    content: str,
    source: str,
) -> str:
    payload = f"{principal_id}|{target_ref_hash}|{kind}|{source}|{content}".encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()[:24]


def _proposal_reason(kind: str) -> str:
    if kind == "open_loop":
        return "Marked open loop from selected target thread preview"
    if kind == "profile_fact":
        return "Marked profile fact from selected target thread preview"
    return "Marked preference from selected target thread preview"


def _proposal_confidence(kind: str) -> float:
    if kind == "open_loop":
        return 0.92
    if kind == "profile_fact":
        return 0.78
    return 0.82


def _prompt_reason(kind: str) -> str:
    if kind == "open_loop":
        return "active open loop for selected target"
    if kind == "profile_fact":
        return "approved profile fact for selected target"
    return "approved preference for selected target"


def _safe_hash(value: str | None) -> str | None:
    clean = (value or "").strip().lower()
    if HEX_HASH.fullmatch(clean):
        return clean
    return None


def _safe_target_label(value: str | None) -> str | None:
    clean = re.sub(r"\s+", " ", (value or "").strip())
    if not clean or len(clean) > 120:
        return None
    return clean


def _normalize_note_content(value: str) -> str | None:
    clean = re.sub(r"\s+", " ", value).strip().strip("\"'")
    if not clean or BLOCKED_CONTENT.search(clean):
        return None
    if len(clean) > 500:
        clean = clean[:497].rstrip() + "..."
    if clean[-1] not in {".", "!", "?"}:
        clean += "."
    return clean


def _safe_reviewer(value: str) -> str:
    clean = re.sub(r"\s+", "-", value.strip().lower())
    clean = re.sub(r"[^a-z0-9@._-]+", "", clean)
    return clean[:128]
