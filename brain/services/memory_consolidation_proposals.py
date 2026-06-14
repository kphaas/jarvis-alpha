"""Reviewed proposal lane for ADR-0026 memory consolidation.

This module turns the existing read-only Dream consolidation candidates into
reviewable proposal rows and T5 approval queue items. It does not execute
archive, promote, merge, or procedural-memory writes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import asyncpg

MEMORY_CONSOLIDATION_APPROVAL_ACTION_CLASSES = ("memory_consolidation_reviewed_write",)
MEMORY_CONSOLIDATION_APPROVAL_TIER = "T5"

EXECUTABLE_ACTIONS: dict[str, str] = {
    "review_for_semantic_promotion": "promote_episodic_to_semantic",
    # ADR-0026: decay is the planner name; archive_working is the executor name.
    "review_for_working_decay": "archive_working",
}
INFORMATIONAL_ACTIONS: dict[str, str] = {
    "merge_duplicate_semantic": "merge_duplicate_semantic",
    "review_for_procedural_memory": "review_for_procedural_memory",
}
REPORT_BUCKETS = (
    "promotion_candidates",
    "decay_candidates",
    "semantic_duplicate_groups",
    "procedural_candidates",
)


class UnknownConsolidationActionError(ValueError):
    """Raised when a planner candidate uses an unsupported action."""


@dataclass(frozen=True, slots=True)
class MemoryConsolidationProposalRecord:
    user_id: str
    candidate_id: str
    candidate_action: str
    proposed_action: str
    executable: bool
    source_memory_ids: tuple[str, ...]
    evidence: dict[str, Any]
    parameters_hash: str

    @property
    def initial_status(self) -> str:
        return "pending_review" if self.executable else "informational"


@dataclass(frozen=True, slots=True)
class PersistedMemoryConsolidationProposal:
    proposal_id: str
    candidate_id: str
    candidate_action: str
    proposed_action: str
    executable: bool
    status: str
    approval_queue_id: str | None
    parameters_hash: str


def build_memory_consolidation_proposal_records(
    report: dict[str, Any],
) -> list[MemoryConsolidationProposalRecord]:
    """Build deterministic proposal records from a read-only Dream report."""

    user_id = str(report.get("canonical_user_id") or report.get("user_id") or "")
    if not user_id:
        raise ValueError("memory consolidation report missing user_id")

    records: list[MemoryConsolidationProposalRecord] = []
    for candidate in _iter_report_candidates(report):
        action = str(candidate.get("action") or "")
        proposed_action = _proposed_action(action)
        executable = action in EXECUTABLE_ACTIONS
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            raise ValueError("memory consolidation candidate missing candidate_id")
        source_memory_ids = _source_memory_ids(candidate)
        evidence = _candidate_evidence(candidate)
        parameters_hash = _proposal_parameters_hash(
            user_id=user_id,
            candidate_id=candidate_id,
            candidate_action=action,
            proposed_action=proposed_action,
            source_memory_ids=source_memory_ids,
        )
        records.append(
            MemoryConsolidationProposalRecord(
                user_id=user_id,
                candidate_id=candidate_id,
                candidate_action=action,
                proposed_action=proposed_action,
                executable=executable,
                source_memory_ids=source_memory_ids,
                evidence=evidence,
                parameters_hash=parameters_hash,
            )
        )
    return records


async def create_reviewed_memory_consolidation_proposals(
    conn: asyncpg.Connection,
    *,
    report: dict[str, Any],
    actor_sub: str,
    actor_type: str = "user",
) -> list[PersistedMemoryConsolidationProposal]:
    """Persist proposals and queue executable ones for T5 approval.

    Idempotency is based on the active proposal tuple
    ``(user_id, candidate_id, candidate_action)``. Re-running the same report
    refreshes evidence but does not create duplicate active proposals or queue
    rows.
    """

    records = build_memory_consolidation_proposal_records(report)
    persisted: list[PersistedMemoryConsolidationProposal] = []

    for record in records:
        row = await conn.fetchrow(
            """
            INSERT INTO public.alpha_memory_consolidation_proposals (
                user_id,
                candidate_id,
                candidate_action,
                proposed_action,
                executable,
                status,
                source_memory_ids,
                evidence,
                parameters_hash
            )
            VALUES (
                $1::uuid,
                $2,
                $3,
                $4,
                $5,
                $6,
                $7::text[],
                $8::jsonb,
                $9
            )
            ON CONFLICT (
                user_id,
                candidate_id,
                candidate_action
            )
            WHERE status IN (
                'pending_review',
                'queued',
                'informational',
                'approved'
            )
            DO UPDATE SET
                source_memory_ids = EXCLUDED.source_memory_ids,
                evidence = EXCLUDED.evidence,
                parameters_hash = EXCLUDED.parameters_hash,
                updated_at = NOW()
            RETURNING
                id::text,
                status,
                executable,
                approval_queue_id::text
            """,
            record.user_id,
            record.candidate_id,
            record.candidate_action,
            record.proposed_action,
            record.executable,
            record.initial_status,
            list(record.source_memory_ids),
            json.dumps(record.evidence, sort_keys=True),
            record.parameters_hash,
        )
        if row is None:
            raise RuntimeError("proposal insert returned no row")

        proposal_id = str(row["id"])
        approval_queue_id = row["approval_queue_id"]
        status = str(row["status"])
        if record.executable and approval_queue_id is None:
            approval_queue_id = await enqueue_memory_consolidation_approval(
                conn,
                proposal_id=proposal_id,
                record=record,
                actor_sub=actor_sub,
                actor_type=actor_type,
            )
            await conn.execute(
                """
                UPDATE public.alpha_memory_consolidation_proposals
                   SET approval_queue_id = $1::uuid,
                       status = 'queued',
                       updated_at = NOW()
                 WHERE id = $2::uuid
                   AND approval_queue_id IS NULL
                """,
                approval_queue_id,
                proposal_id,
            )
            status = "queued"

        if record.proposed_action == "archive_working" and status in {
            "pending_review",
            "queued",
            "approved",
        }:
            await conn.fetchval(
                "SELECT public.mark_memory_consolidation_archive_hold($1::uuid)",
                proposal_id,
            )

        persisted.append(
            PersistedMemoryConsolidationProposal(
                proposal_id=proposal_id,
                candidate_id=record.candidate_id,
                candidate_action=record.candidate_action,
                proposed_action=record.proposed_action,
                executable=record.executable,
                status=status,
                approval_queue_id=str(approval_queue_id) if approval_queue_id else None,
                parameters_hash=record.parameters_hash,
            )
        )

    return persisted


async def enqueue_memory_consolidation_approval(
    conn: asyncpg.Connection,
    *,
    proposal_id: str,
    record: MemoryConsolidationProposalRecord,
    actor_sub: str,
    actor_type: str,
) -> str:
    """Queue a proposal-specific T5 approval without storing memory text."""

    description = (
        "Memory consolidation reviewed write: "
        f"{record.proposed_action} for {len(record.source_memory_ids)} source item(s)"
    )
    try:
        queue_id = await conn.fetchval(
            """
            SELECT public.enqueue_approval_request(
                $1::text[], $2, $3, $4, $5, $6, $7
            )
            """,
            list(MEMORY_CONSOLIDATION_APPROVAL_ACTION_CLASSES),
            MEMORY_CONSOLIDATION_APPROVAL_TIER,
            actor_sub,
            actor_type,
            description,
            record.parameters_hash,
            f"memory-consolidation:{proposal_id}:{uuid4().hex}",
        )
    except asyncpg.UniqueViolationError:
        queue_id = await conn.fetchval(
            """
            SELECT id::text
              FROM public.alpha_approval_queue
             WHERE actor_sub = $1
               AND parameters_hash = $2
               AND status = 'pending'
             ORDER BY requested_at DESC
             LIMIT 1
            """,
            actor_sub,
            record.parameters_hash,
        )
        if queue_id is None:
            raise
    if queue_id is None:
        raise RuntimeError("enqueue_approval_request returned no queue id")
    return str(queue_id)


def _iter_report_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for bucket in REPORT_BUCKETS:
        for candidate in report.get(bucket) or []:
            candidates.append(dict(candidate))
    return candidates


def _proposed_action(candidate_action: str) -> str:
    if candidate_action in EXECUTABLE_ACTIONS:
        return EXECUTABLE_ACTIONS[candidate_action]
    if candidate_action in INFORMATIONAL_ACTIONS:
        return INFORMATIONAL_ACTIONS[candidate_action]
    raise UnknownConsolidationActionError(
        f"Unknown memory consolidation action: {candidate_action}"
    )


def _source_memory_ids(candidate: dict[str, Any]) -> tuple[str, ...]:
    if candidate.get("memory_ids"):
        return tuple(str(value) for value in candidate["memory_ids"] if value)
    if candidate.get("memory_id"):
        return (str(candidate["memory_id"]),)
    return ()


def _candidate_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate.get("candidate_id"),
        "action": candidate.get("action"),
        "memory_id": candidate.get("memory_id"),
        "memory_ids": candidate.get("memory_ids"),
        "tier": candidate.get("tier"),
        "reason": candidate.get("reason"),
        "confidence": candidate.get("confidence"),
        "summary": candidate.get("summary"),
        "normalized_fact": candidate.get("normalized_fact"),
        "count": candidate.get("count"),
    }


def _proposal_parameters_hash(
    *,
    user_id: str,
    candidate_id: str,
    candidate_action: str,
    proposed_action: str,
    source_memory_ids: tuple[str, ...],
) -> str:
    payload = {
        "candidate_action": candidate_action,
        "candidate_id": candidate_id,
        "proposed_action": proposed_action,
        "source_memory_ids": list(source_memory_ids),
        "user_id": user_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_memory_user_id(value: str | UUID) -> str:
    """Validate UUID-like user ids for proposal route responses."""

    return str(UUID(str(value)))
