"""Reviewed temporal graph proposals from Dream and Buddy signals.

This module is intentionally proposal-only. It turns non-explicit memory
signals into T5-reviewed temporal graph proposals, but it never executes graph
writes or bypasses the existing approval gateway.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

import asyncpg

GRAPH_EXTRACTION_PIPELINE = "dream_buddy_graph_extraction"
GRAPH_EXTRACTION_SOURCE_SURFACE = "memory_graph_extraction"
MAX_GRAPH_EXTRACTION_RECORDS = 20
MAX_LABEL_PREVIEW = 160

_SPACE = re.compile(r"\s+")

_DREAM_GRAPH_ACTIONS: dict[str, tuple[str, str]] = {
    "review_for_semantic_promotion": ("fact", "Dream fact candidate"),
    "review_for_procedural_memory": ("task", "Dream procedure candidate"),
}


@dataclass(frozen=True, slots=True)
class MemoryGraphExtractionRecord:
    principal_id: str
    source_kind: str
    source_candidate_id: str
    proposed_action: str
    object_type: str
    label_preview: str
    payload: dict[str, Any]
    reason: str
    parameters_hash: str


@dataclass(frozen=True, slots=True)
class PersistedMemoryGraphExtractionProposal:
    proposal_id: str | None
    source_kind: str
    source_candidate_id: str
    proposed_action: str
    object_type: str
    status: str
    approval_queue_id: str | None
    parameters_hash: str
    existing: bool


def build_memory_graph_extraction_records(
    report: dict[str, Any],
    *,
    buddy_events: list[dict[str, Any]] | None = None,
) -> list[MemoryGraphExtractionRecord]:
    """Build deterministic graph proposal records from Dream and Buddy signals."""

    raw_principal_id = str(
        report.get("canonical_user_id") or report.get("user_id") or ""
    ).strip()
    if not raw_principal_id:
        raise ValueError("memory graph extraction report missing user_id")
    principal_id = _canonical_memory_user_id(raw_principal_id)

    records: list[MemoryGraphExtractionRecord] = []
    for candidate in _iter_dream_candidates(report):
        record = _dream_candidate_record(principal_id, candidate)
        if record is not None:
            records.append(record)

    for event in buddy_events or []:
        record = _buddy_event_record(principal_id, event)
        if record is not None:
            records.append(record)

    return records[:MAX_GRAPH_EXTRACTION_RECORDS]


async def create_memory_graph_extraction_proposals(
    conn: asyncpg.Connection,
    *,
    report: dict[str, Any],
    actor_sub: str,
    buddy_events: list[dict[str, Any]] | None = None,
) -> list[PersistedMemoryGraphExtractionProposal]:
    """Persist graph extraction proposals while preserving review gates.

    The temporal graph SECDEF function does not currently expose a conflict key,
    so this service performs active-proposal de-duplication by source pipeline
    and candidate id before queueing a new reviewed graph write.
    """

    records = build_memory_graph_extraction_records(report, buddy_events=buddy_events)
    persisted: list[PersistedMemoryGraphExtractionProposal] = []

    for record in records:
        existing = await _existing_graph_proposal(conn, record)
        if existing is not None:
            persisted.append(
                PersistedMemoryGraphExtractionProposal(
                    proposal_id=str(existing["proposal_id"]),
                    source_kind=record.source_kind,
                    source_candidate_id=record.source_candidate_id,
                    proposed_action=record.proposed_action,
                    object_type=record.object_type,
                    status=str(existing["status"]),
                    approval_queue_id=_optional_str(existing["approval_queue_id"]),
                    parameters_hash=str(existing["parameters_hash"]),
                    existing=True,
                )
            )
            continue

        result = _json_result(
            await conn.fetchval(
                """
                SELECT public.propose_memory_graph_write(
                    $1::uuid,
                    $2,
                    $3,
                    $4::jsonb,
                    $5,
                    $6,
                    $7
                )
                """,
                record.principal_id,
                record.proposed_action,
                record.object_type,
                json.dumps(record.payload, sort_keys=True),
                GRAPH_EXTRACTION_SOURCE_SURFACE,
                actor_sub,
                record.reason,
            )
        )
        persisted.append(
            PersistedMemoryGraphExtractionProposal(
                proposal_id=_optional_str(result.get("proposal_id")),
                source_kind=record.source_kind,
                source_candidate_id=record.source_candidate_id,
                proposed_action=record.proposed_action,
                object_type=record.object_type,
                status=str(result.get("status") or "not_queued"),
                approval_queue_id=_optional_str(result.get("approval_queue_id")),
                parameters_hash=str(
                    result.get("parameters_hash") or record.parameters_hash
                ),
                existing=False,
            )
        )

    return persisted


async def collect_buddy_graph_signal_events(
    conn: asyncpg.Connection,
    user_id: str | UUID,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Collect bounded high-priority Buddy memory events for graph review."""

    principal_id = _canonical_memory_user_id(user_id)
    rows = await conn.fetch(
        """
        SELECT
            id::text,
            event_type,
            title,
            priority,
            source,
            COALESCE(payload, '{}'::jsonb) AS payload,
            created_at
        FROM public.alpha_buddy_events
        WHERE user_id = $1
          AND read = false
          AND priority >= 3
          AND created_at >= now() - INTERVAL '7 days'
          AND NOT (
              COALESCE(payload, '{}'::jsonb) ? 'memory_suppression'
              OR COALESCE(payload, '{}'::jsonb) ? 'memory_admin_suppression'
          )
          AND (
              source IN (
                  'semantic_memory_review',
                  'memory_observability_monitor',
                  'memory_consolidation',
                  'spark_memory_grounding'
              )
              OR COALESCE(payload, '{}'::jsonb) ? 'memory_id'
              OR COALESCE(payload, '{}'::jsonb) ? 'proposal_id'
              OR COALESCE(payload, '{}'::jsonb) ? 'fingerprint'
              OR title ILIKE '%memory%'
          )
        ORDER BY priority DESC, created_at DESC, id DESC
        LIMIT $2
        """,
        principal_id,
        limit,
    )
    return [dict(row) for row in rows]


def memory_graph_extraction_summary_body(
    *,
    user_count: int,
    candidate_count: int,
    queued_count: int,
    existing_count: int,
) -> str:
    """Buddy-safe graph extraction summary without raw memory text."""

    return (
        f"Temporal graph extraction reviewed {candidate_count} candidate(s) "
        f"across {user_count} user(s). Queued {queued_count}; reused "
        f"{existing_count} existing open proposal(s). Execution remains T5-gated."
    )


def _iter_dream_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for bucket in ("promotion_candidates", "procedural_candidates"):
        for candidate in report.get(bucket) or []:
            candidates.append(dict(candidate))
    return candidates


def _dream_candidate_record(
    principal_id: str,
    candidate: dict[str, Any],
) -> MemoryGraphExtractionRecord | None:
    action = str(candidate.get("action") or "")
    node = _DREAM_GRAPH_ACTIONS.get(action)
    candidate_id = str(candidate.get("candidate_id") or "")
    label_preview = _clean_preview(str(candidate.get("summary") or ""))
    if node is None or not candidate_id or not label_preview:
        return None

    node_type, reason_prefix = node
    memory_ids = _source_memory_ids(candidate)
    source_candidate_id = f"dream:{candidate_id}"
    confidence = _confidence(candidate.get("confidence"), default=0.75)
    payload = {
        "node_type": node_type,
        "label_preview": label_preview,
        "label_hash": _label_hash(label_preview),
        "external_ref_type": "alpha_conversation_memory" if memory_ids else None,
        "external_ref_id": memory_ids[0] if len(memory_ids) == 1 else None,
        "source": "dream",
        "confidence": confidence,
        "properties": {
            "extraction_kind": "dream_consolidation",
            "candidate_action": action,
            "tier": _optional_str(candidate.get("tier")),
            "reason": _optional_str(candidate.get("reason")),
            "source_memory_count": len(memory_ids),
            "source_memory_ids": memory_ids,
        },
        "provenance": {
            "source_pipeline": GRAPH_EXTRACTION_PIPELINE,
            "source_candidate_id": source_candidate_id,
            "source_candidate_action": action,
            "source_memory_ids": memory_ids,
        },
    }
    return _record(
        principal_id=principal_id,
        source_kind="dream",
        source_candidate_id=source_candidate_id,
        proposed_action="create_node",
        object_type="node",
        label_preview=label_preview,
        payload=_without_none(payload),
        reason=f"{reason_prefix}: {candidate.get('reason') or action}",
    )


def _buddy_event_record(
    principal_id: str,
    event: dict[str, Any],
) -> MemoryGraphExtractionRecord | None:
    event_id = str(event.get("id") or "")
    title = _clean_preview(str(event.get("title") or ""))
    if not event_id or not title:
        return None
    priority = _int(event.get("priority"))
    if priority < 3:
        return None

    payload_value = event.get("payload")
    payload_meta = payload_value if isinstance(payload_value, dict) else {}
    source_candidate_id = f"buddy:{event_id}"
    label_preview = _clean_preview(f"Buddy signal: {title}")
    payload = {
        "node_type": "other",
        "label_preview": label_preview,
        "label_hash": _label_hash(label_preview),
        "external_ref_type": "alpha_buddy_events",
        "external_ref_id": event_id,
        "source": "buddy",
        "confidence": 0.7,
        "properties": {
            "extraction_kind": "buddy_event_signal",
            "event_type": _optional_str(event.get("event_type")),
            "event_priority": priority,
            "event_source": _optional_str(event.get("source")),
            "memory_id_present": "memory_id" in payload_meta,
            "proposal_id_present": "proposal_id" in payload_meta,
            "fingerprint_present": "fingerprint" in payload_meta,
        },
        "provenance": {
            "source_pipeline": GRAPH_EXTRACTION_PIPELINE,
            "source_candidate_id": source_candidate_id,
            "buddy_event_id": event_id,
        },
    }
    return _record(
        principal_id=principal_id,
        source_kind="buddy",
        source_candidate_id=source_candidate_id,
        proposed_action="create_node",
        object_type="node",
        label_preview=label_preview,
        payload=_without_none(payload),
        reason="High-priority Buddy memory event",
    )


def _record(
    *,
    principal_id: str,
    source_kind: str,
    source_candidate_id: str,
    proposed_action: str,
    object_type: str,
    label_preview: str,
    payload: dict[str, Any],
    reason: str,
) -> MemoryGraphExtractionRecord:
    return MemoryGraphExtractionRecord(
        principal_id=principal_id,
        source_kind=source_kind,
        source_candidate_id=source_candidate_id,
        proposed_action=proposed_action,
        object_type=object_type,
        label_preview=label_preview,
        payload=payload,
        reason=reason[:300],
        parameters_hash=_record_parameters_hash(
            principal_id=principal_id,
            proposed_action=proposed_action,
            object_type=object_type,
            payload=payload,
        ),
    )


async def _existing_graph_proposal(
    conn: asyncpg.Connection,
    record: MemoryGraphExtractionRecord,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT
            id::text AS proposal_id,
            status,
            approval_queue_id::text,
            parameters_hash
        FROM public.alpha_memory_graph_proposals
        WHERE principal_id = $1::uuid
          AND proposed_action = $2
          AND object_type = $3
          AND status IN ('pending_review', 'queued', 'approved')
          AND payload->'provenance'->>'source_pipeline' = $4
          AND payload->'provenance'->>'source_candidate_id' = $5
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        """,
        record.principal_id,
        record.proposed_action,
        record.object_type,
        GRAPH_EXTRACTION_PIPELINE,
        record.source_candidate_id,
    )


def _canonical_memory_user_id(value: str | UUID) -> str:
    if isinstance(value, UUID):
        return str(value)
    try:
        return str(UUID(str(value)))
    except ValueError:
        return str(uuid5(NAMESPACE_DNS, str(value)))


def _source_memory_ids(candidate: dict[str, Any]) -> list[str]:
    if candidate.get("memory_ids"):
        return [str(value) for value in candidate["memory_ids"] if value]
    if candidate.get("memory_id"):
        return [str(candidate["memory_id"])]
    return []


def _clean_preview(value: str) -> str:
    cleaned = _SPACE.sub(" ", value.strip())
    return cleaned[:MAX_LABEL_PREVIEW]


def _label_hash(value: str) -> str:
    return hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()


def _record_parameters_hash(
    *,
    principal_id: str,
    proposed_action: str,
    object_type: str,
    payload: dict[str, Any],
) -> str:
    encoded = json.dumps(
        {
            "object_type": object_type,
            "payload": payload,
            "principal_id": principal_id,
            "proposed_action": proposed_action,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_result(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    return {}


def _without_none(value: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if item is None:
            continue
        if isinstance(item, dict):
            cleaned[key] = _without_none(item)
        else:
            cleaned[key] = item
    return cleaned


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _confidence(value: object, *, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, round(confidence, 3)))


def _int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
