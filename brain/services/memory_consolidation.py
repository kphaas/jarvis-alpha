"""Read-only Memory 2.0 consolidation planning.

Dream owns reflection and consolidation. This module only builds a reviewed
backlog: promote, dedupe, decay, and procedural-memory candidates. It never
writes memory rows.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

import asyncpg

PROMOTION_IMPORTANCE_THRESHOLD = 0.7
PROMOTION_ACCESS_THRESHOLD = 3
STALE_WORKING_HOURS = 20
MAX_CANDIDATES_PER_BUCKET = 10

_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_PROCEDURAL_SIGNAL = re.compile(
    r"\b("
    r"how i|how ken|my process|workflow|playbook|runbook|standard|"
    r"decision pattern|approval gate|guardrail|when i|if i|always|never|"
    r"do it right|best of breed|step 1|first then|before i"
    r")\b",
    re.IGNORECASE,
)
_INJECTION_OR_SECRET_SIGNAL = re.compile(
    r"\b("
    r"ignore previous|ignore all previous|system prompt|developer message|"
    r"jailbreak|password|token|secret|private key|api key|raw thread"
    r")\b",
    re.IGNORECASE,
)


def _canonical_memory_user_id(user_id: str | UUID) -> UUID:
    if isinstance(user_id, UUID):
        return user_id
    try:
        return UUID(str(user_id))
    except ValueError:
        return uuid5(NAMESPACE_DNS, str(user_id))


def _text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _float(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bool(row: dict[str, Any], key: str) -> bool:
    value = row.get(key)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _dt(row: dict[str, Any], key: str) -> datetime | None:
    value = row.get(key)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _normalized(value: str) -> str:
    lowered = value.strip().casefold()
    lowered = _PUNCT.sub(" ", lowered)
    return _SPACE.sub(" ", lowered).strip()


def _candidate_id(action: str, row_id: str, content: str) -> str:
    digest = hashlib.sha256(f"{action}:{row_id}:{content}".encode("utf-8")).hexdigest()
    return digest[:16]


def _conversation_candidate(
    *,
    action: str,
    row: dict[str, Any],
    reason: str,
    confidence: float,
) -> dict[str, Any]:
    summary = _text(row, "summary", "content", "fact")
    row_id = _text(row, "id", "memory_id") or _candidate_id(action, "", summary)
    return {
        "candidate_id": _candidate_id(action, row_id, summary),
        "action": action,
        "memory_id": row_id,
        "tier": _text(row, "tier") or "unknown",
        "summary": summary[:500],
        "reason": reason,
        "confidence": round(confidence, 3),
        "requires_review": True,
    }


def _semantic_duplicates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        fact = _text(row, "fact", "summary", "content")
        key = _normalized(fact)
        if not key:
            continue
        buckets.setdefault(key, []).append(row)

    duplicate_groups: list[dict[str, Any]] = []
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        first = group[0]
        duplicate_groups.append(
            {
                "candidate_id": _candidate_id(
                    "merge_duplicate_semantic",
                    _text(first, "id") or key,
                    key,
                ),
                "action": "merge_duplicate_semantic",
                "normalized_fact": key,
                "count": len(group),
                "memory_ids": [_text(row, "id") for row in group if _text(row, "id")],
                "requires_review": True,
            }
        )
    return duplicate_groups[:MAX_CANDIDATES_PER_BUCKET]


def build_memory_consolidation_report(
    *,
    user_id: str | UUID,
    semantic_rows: list[dict[str, Any]],
    conversation_rows: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a reviewed Dream consolidation backlog without mutating memory."""

    timestamp = now or datetime.now(timezone.utc)
    duplicate_groups = _semantic_duplicates(semantic_rows)
    promotion_candidates: list[dict[str, Any]] = []
    decay_candidates: list[dict[str, Any]] = []
    procedural_candidates: list[dict[str, Any]] = []
    blocked_candidate_count = 0

    for row in conversation_rows:
        summary = _text(row, "summary", "content")
        if not summary:
            continue
        if _INJECTION_OR_SECRET_SIGNAL.search(summary):
            blocked_candidate_count += 1
            continue

        tier = _text(row, "tier").lower()
        importance = _float(row, "importance_score")
        access_count = _int(row, "access_count")
        persistent = _bool(row, "persistent")

        if tier in {"working", "episodic"} and (
            importance >= PROMOTION_IMPORTANCE_THRESHOLD
            or access_count >= PROMOTION_ACCESS_THRESHOLD
        ):
            promotion_candidates.append(
                _conversation_candidate(
                    action="review_for_semantic_promotion",
                    row=row,
                    reason=(
                        "high importance"
                        if importance >= PROMOTION_IMPORTANCE_THRESHOLD
                        else "repeated access"
                    ),
                    confidence=max(importance, min(0.95, 0.55 + access_count * 0.1)),
                )
            )

        created_at = _dt(row, "created_at")
        if tier == "working" and not persistent and created_at is not None:
            age_hours = (timestamp - created_at).total_seconds() / 3600.0
            if age_hours >= STALE_WORKING_HOURS:
                decay_candidates.append(
                    _conversation_candidate(
                        action="review_for_working_decay",
                        row=row,
                        reason=f"working memory older than {STALE_WORKING_HOURS}h",
                        confidence=min(0.95, age_hours / 48.0),
                    )
                )

        if _PROCEDURAL_SIGNAL.search(summary):
            procedural_candidates.append(
                _conversation_candidate(
                    action="review_for_procedural_memory",
                    row=row,
                    reason="procedural or workflow signal",
                    confidence=max(0.7, importance),
                )
            )

    promotion_candidates = promotion_candidates[:MAX_CANDIDATES_PER_BUCKET]
    decay_candidates = decay_candidates[:MAX_CANDIDATES_PER_BUCKET]
    procedural_candidates = procedural_candidates[:MAX_CANDIDATES_PER_BUCKET]
    candidate_count = (
        len(promotion_candidates)
        + len(decay_candidates)
        + len(procedural_candidates)
        + len(duplicate_groups)
    )

    return {
        "user_id": str(user_id),
        "canonical_user_id": str(_canonical_memory_user_id(user_id)),
        "status": "review_ready" if candidate_count else "clear",
        "mode": "read_only_review_required",
        "candidate_count": candidate_count,
        "blocked_candidate_count": blocked_candidate_count,
        "promotion_candidates": promotion_candidates,
        "semantic_duplicate_groups": duplicate_groups,
        "decay_candidates": decay_candidates,
        "procedural_candidates": procedural_candidates,
        "write_actions_enabled": False,
    }


def memory_consolidation_summary_body(report: dict[str, Any]) -> str:
    """Buddy-safe summary with counts only, not raw memory contents."""

    return (
        "Dream memory consolidation backlog for "
        f"{report.get('user_id')}: "
        f"{len(report.get('promotion_candidates') or [])} promotion, "
        f"{len(report.get('semantic_duplicate_groups') or [])} duplicate, "
        f"{len(report.get('decay_candidates') or [])} stale working, "
        f"{len(report.get('procedural_candidates') or [])} procedural candidates. "
        f"Blocked suspicious candidates: {int(report.get('blocked_candidate_count') or 0)}. "
        "Writes are disabled; every consolidation action requires review."
    )


async def collect_memory_consolidation_report(
    conn: asyncpg.Connection,
    user_id: str | UUID,
    *,
    semantic_limit: int = 200,
    conversation_limit: int = 200,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect a bounded memory snapshot and build a Dream review plan."""

    canonical_user_id = _canonical_memory_user_id(user_id)
    semantic_rows = await conn.fetch(
        """
        SELECT id::text, fact, category, source, created_at, updated_at
        FROM alpha_semantic_memory
        WHERE user_id = $1
        ORDER BY updated_at DESC, created_at DESC
        LIMIT $2
        """,
        canonical_user_id,
        semantic_limit,
    )
    conversation_rows = await conn.fetch(
        """
        SELECT id::text, tier, session_id, summary, memory_type AS role,
               persistent, importance_score, access_count,
               created_at, last_accessed_at
        FROM alpha_conversation_memory
        WHERE user_id = $1
          AND tier IN ('working', 'episodic')
        ORDER BY created_at DESC
        LIMIT $2
        """,
        str(canonical_user_id),
        conversation_limit,
    )
    return build_memory_consolidation_report(
        user_id=str(user_id),
        semantic_rows=[dict(row) for row in semantic_rows],
        conversation_rows=[dict(row) for row in conversation_rows],
        now=now,
    )
