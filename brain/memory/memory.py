from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

import asyncpg

from brain.services.spark_memory_grounding import load_spark_memory_grounding
from brain.services.spark_personality_memory import (
    fetch_personality_memory,
    personality_memory_context,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_memory")

SEMANTIC_CAP = 50
EPISODIC_LIMIT = 5
WORKING_LIMIT = 10


class MemoryService:
    # ------------------------------------------------------------------
    # IMPORTANCE SCORER — heuristic, no LLM call
    # Stanford/Mem0 pattern: score at write time, use at retrieval
    # ------------------------------------------------------------------

    CHILD_NAMES = re.compile(r"\b(ryleigh|sloane)\b", re.IGNORECASE)
    SAFETY_KEYWORDS = re.compile(
        r"\b(allerg|medicat|emergenc|danger|restrict|forbid|not\s+allowed)",
        re.IGNORECASE,
    )
    EXPLICIT_REMEMBER = re.compile(
        r"\b(remember|always|never|don.t forget|important)\b",
        re.IGNORECASE,
    )
    PREFERENCE_KEYWORDS = re.compile(
        r"\b(prefer|favorite|like|dislike|hate|love|enjoy|avoid)\b",
        re.IGNORECASE,
    )
    NOISE_PATTERN = re.compile(
        r"^(ok|okay|thanks|thank you|got it|sure|yes|no|yep|nope|k|cool|nice|good|great|alright|sounds good|perfect|fine|hmm|hm|ah|oh|lol|haha)[\.\!\?]?$",
        re.IGNORECASE,
    )

    def _score_importance(self, text: str) -> float:
        """
        Heuristic importance scoring (0.0 — 1.0).
        Modeled after Stanford Generative Agents + Mem0 production pattern.
        Higher = more likely to survive eviction and promote to semantic.
        """
        stripped = (text or "").strip()
        if not stripped:
            return 0.05

        # Noise gate — trivial acknowledgments (before short-text discard)
        if self.NOISE_PATTERN.match(stripped):
            return 0.1

        if len(stripped) < 5:
            return 0.05

        score = 0.5  # baseline for normal conversation

        # Child safety — highest priority (JARVIS invariant)
        if self.CHILD_NAMES.search(stripped) and self.SAFETY_KEYWORDS.search(stripped):
            return 0.95

        # Length adjustment before preference/explicit boosts (short generic lines stay low)
        if len(stripped) > 200:
            score = max(score, score + 0.1)
        elif len(stripped) < 20:
            score = min(score, 0.3)

        # Explicit memory request
        if self.EXPLICIT_REMEMBER.search(stripped):
            score = max(score, 0.8)

        # Preference / relationship signal
        if self.PREFERENCE_KEYWORDS.search(stripped):
            score = max(score, 0.7)

        # Child name without safety keyword — still elevated
        if self.CHILD_NAMES.search(stripped):
            score = max(score, 0.75)

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # CONTEXT BUILDER — called before every /v1/ask
    # ------------------------------------------------------------------

    async def build_context(
        self,
        conn: asyncpg.Connection,
        user_id: UUID,
        prompt: str,
        session_id: str,
        embedding: list[float],
        principal_id: str | None = None,
    ) -> str:
        spark_grounding = await self._get_spark_grounding(conn, principal_id)
        semantic = await self._get_semantic(conn, user_id, prompt=prompt)
        episodic = await self._get_episodic(conn, user_id, embedding)
        working = await self._get_working(conn, session_id)

        parts = []

        if spark_grounding:
            parts.append(spark_grounding)

        if semantic:
            facts = "\n".join(f"- {r['fact']}" for r in semantic)
            parts.append(f"[ALWAYS KNOWN]\n{facts}")

        if episodic:
            memories = "\n".join(f"- {r['summary']}" for r in episodic)
            parts.append(f"[RELEVANT PAST]\n{memories}")

        if working:
            turns = "\n".join(f"{r['role'].upper()}: {r['summary']}" for r in working)
            parts.append(f"[RECENT CONVERSATION]\n{turns}")

        return "\n\n".join(parts)

    async def _get_spark_grounding(
        self,
        conn: asyncpg.Connection,
        principal_id: str | None,
    ) -> str:
        try:
            rows = await fetch_personality_memory(conn, principal_id)
            context = personality_memory_context(rows)
            if context:
                return context
        except Exception as exc:
            logger.warning(
                "spark_personality_memory_unavailable",
                extra={
                    "event": "spark_personality_memory_unavailable",
                    "error_class": exc.__class__.__name__,
                    "principal_id": principal_id or "",
                },
            )

        try:
            grounding = load_spark_memory_grounding(principal_id=principal_id)
        except Exception as exc:
            logger.warning(
                "spark_memory_grounding_unavailable",
                extra={
                    "event": "spark_memory_grounding_unavailable",
                    "error_class": exc.__class__.__name__,
                    "principal_id": principal_id or "",
                },
            )
            return ""
        if grounding is None:
            return ""
        return grounding.to_context_block()

    # ------------------------------------------------------------------
    # TIER 1 — SEMANTIC (always injected, full read, no search)
    # ------------------------------------------------------------------

    async def _get_semantic(
        self,
        conn: asyncpg.Connection,
        user_id: UUID,
        *,
        prompt: str = "",
    ) -> list[dict]:
        query = (prompt or "").strip()
        if query:
            rows = await conn.fetch(
                """
                WITH ranked AS (
                    SELECT
                        fact,
                        category,
                        source,
                        created_at,
                        updated_at,
                        ts_rank_cd(
                            to_tsvector('simple', fact || ' ' || category),
                            websearch_to_tsquery('simple', $3)
                        ) AS text_rank,
                        CASE category
                            WHEN 'constraint' THEN 0.25
                            WHEN 'health' THEN 0.20
                            WHEN 'child_profile' THEN 0.20
                            WHEN 'preference' THEN 0.10
                            ELSE 0.0
                        END AS category_boost
                    FROM alpha_semantic_memory
                    WHERE user_id = $1
                      AND COALESCE(review_status, 'active') IN ('active', 'pending_review')
                )
                SELECT fact, category, source
                FROM ranked
                ORDER BY (text_rank + category_boost) DESC,
                         updated_at DESC,
                         created_at DESC
                LIMIT $2
                """,
                user_id,
                SEMANTIC_CAP,
                query,
            )
            return [dict(r) for r in rows]

        rows = await conn.fetch(
            """
            SELECT fact, category, source
            FROM alpha_semantic_memory
            WHERE user_id = $1
              AND COALESCE(review_status, 'active') IN ('active', 'pending_review')
            ORDER BY updated_at DESC, created_at DESC
            LIMIT $2
            """,
            user_id,
            SEMANTIC_CAP,
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # TIER 2 — EPISODIC (vector search, context-triggered)
    # ------------------------------------------------------------------

    async def _get_episodic(
        self,
        conn: asyncpg.Connection,
        user_id: UUID,
        embedding: list[float],
    ) -> list[dict]:
        """
        Weighted retrieval: Stanford Generative Agents pattern.
        score = 0.3 * recency + 0.4 * importance + 0.3 * relevance
        All factors normalized to [0, 1].
        """
        if not embedding:
            return []

        rows = await conn.fetch(
            """
            WITH candidates AS (
                SELECT
                    id,
                    summary,
                    importance_score,
                    last_accessed_at,
                    access_count,
                    1 - (embedding <=> $2::vector) AS cosine_sim
                FROM alpha_conversation_memory
                WHERE user_id = $1
                  AND tier = 'episodic'
            )
            SELECT
                id,
                summary,
                importance_score,
                access_count,
                cosine_sim,
                -- Recency: exponential decay, 0.995^hours since last access
                POWER(0.995, EXTRACT(EPOCH FROM (now() - last_accessed_at)) / 3600.0)
                    AS recency_score,
                -- Final weighted score (Stanford formula)
                (
                    0.3 * POWER(0.995, EXTRACT(EPOCH FROM (now() - last_accessed_at)) / 3600.0)
                  + 0.4 * importance_score
                  + 0.3 * cosine_sim
                ) AS retrieval_score
            FROM candidates
            WHERE cosine_sim > 0.3
            ORDER BY retrieval_score DESC
            LIMIT $3
            """,
            str(user_id),
            str(embedding),
            EPISODIC_LIMIT,
        )

        # Bump access tracking (do not block on result value)
        if rows:
            ids = [r["id"] for r in rows]
            await conn.execute(
                "SELECT public.bump_memory_access($1::uuid[])",
                ids,
            )

        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # TIER 3 — WORKING (last N turns this session)
    # ------------------------------------------------------------------

    async def _get_working(
        self, conn: asyncpg.Connection, session_id: str
    ) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT summary, memory_type as role
            FROM alpha_conversation_memory
            WHERE session_id = $1
              AND tier = 'working'
            ORDER BY created_at DESC
            LIMIT $2
            """,
            session_id,
            WORKING_LIMIT,
        )
        return list(reversed([dict(r) for r in rows]))

    # ------------------------------------------------------------------
    # STORE — save a new turn
    # ------------------------------------------------------------------

    async def store(
        self,
        conn: asyncpg.Connection,
        user_id: UUID,
        session_id: str,
        summary: str,
        role: str,
        embedding: list[float],
        persistent: bool = False,
    ) -> None:
        if not embedding:
            return

        # Write gate — skip noise (Mem0 intelligent filtering pattern)
        importance = self._score_importance(summary)
        if importance <= 0.1:
            return

        tier = "episodic" if persistent else "working"
        await conn.fetchval(
            """
            SELECT public.store_conversation_memory(
              $1, $2, $3, $4, $5::vector(768), $6, $7, $8
            )
            """,
            str(user_id),
            session_id,
            role,
            summary,
            str(embedding),
            tier,
            persistent,
            importance,
        )

    # ------------------------------------------------------------------
    # EXPLICIT SAVE — user says "remember this"
    # Real-time semantic promotion
    # ------------------------------------------------------------------

    async def save_semantic(
        self,
        conn: asyncpg.Connection,
        user_id: UUID,
        fact: str,
        category: str,
        *,
        provenance: dict[str, Any] | None = None,
        review_status: str | None = None,
        review_reason: str | None = None,
    ) -> dict:
        payload = await conn.fetchval(
            """
            SELECT public.save_semantic_memory_with_provenance(
              $1::uuid, $2, $3, $4::jsonb, $5, $6
            )
            """,
            user_id,
            fact,
            category,
            json.dumps(provenance or {}, sort_keys=True),
            review_status,
            review_reason,
        )
        if isinstance(payload, str):
            return json.loads(payload)
        return dict(payload)

    async def review_semantic(
        self,
        conn: asyncpg.Connection,
        user_id: UUID,
        memory_id: UUID,
        action: str,
        reviewed_by: str,
        note: str | None = None,
    ) -> dict:
        payload = await conn.fetchval(
            """
            SELECT public.review_semantic_memory(
              $1::uuid, $2::uuid, $3, $4, $5
            )
            """,
            user_id,
            memory_id,
            action,
            reviewed_by,
            note,
        )
        if isinstance(payload, str):
            return json.loads(payload)
        return dict(payload)

    async def forget_by_topic(
        self, conn: asyncpg.Connection, user_id: UUID, topic: str
    ) -> int:
        return int(
            await conn.fetchval(
                "SELECT public.forget_memory_by_topic($1, $2)",
                str(user_id),
                topic,
            )
        )

    async def forget_working(self, conn: asyncpg.Connection, user_id: UUID) -> int:
        return int(
            await conn.fetchval(
                "SELECT public.forget_working_memory($1)",
                str(user_id),
            )
        )

    async def summarize(
        self,
        conn: asyncpg.Connection,
        user_id: UUID,
        *,
        semantic_limit: int = 20,
        working_limit: int = 10,
    ) -> dict:
        """Return a bounded review snapshot without embeddings or raw internals."""
        semantic_rows = await conn.fetch(
            """
            SELECT id::text, fact, category, source, provenance,
                   review_status, review_reason, reviewed_at, reviewed_by,
                   created_at, updated_at
            FROM alpha_semantic_memory
            WHERE user_id = $1
              AND COALESCE(review_status, 'active') <> 'archived'
            ORDER BY updated_at DESC, created_at DESC
            LIMIT $2
            """,
            user_id,
            semantic_limit,
        )
        semantic_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM alpha_semantic_memory
            WHERE user_id = $1
              AND COALESCE(review_status, 'active') <> 'archived'
            """,
            user_id,
        )
        semantic_review_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM alpha_semantic_memory
            WHERE user_id = $1
              AND review_status = 'pending_review'
            """,
            user_id,
        )
        conversation_counts = await conn.fetch(
            """
            SELECT tier, COUNT(*) AS count
            FROM alpha_conversation_memory
            WHERE user_id = $1
            GROUP BY tier
            """,
            str(user_id),
        )
        working_rows = await conn.fetch(
            """
            SELECT id::text, session_id, summary, memory_type AS role,
                   importance_score, created_at
            FROM alpha_conversation_memory
            WHERE user_id = $1
              AND tier = 'working'
            ORDER BY created_at DESC
            LIMIT $2
            """,
            str(user_id),
            working_limit,
        )
        tier_counts = {
            str(row["tier"]): int(row["count"]) for row in conversation_counts
        }
        return {
            "semantic_count": int(semantic_count or 0),
            "semantic_review_count": int(semantic_review_count or 0),
            "episodic_count": tier_counts.get("episodic", 0),
            "working_count": tier_counts.get("working", 0),
            "semantic": [_semantic_summary_row(row) for row in semantic_rows],
            "working": [dict(row) for row in working_rows],
        }

    async def telemetry(
        self,
        conn: asyncpg.Connection,
        user_id: UUID,
        *,
        recent_limit: int = 20,
    ) -> dict:
        """Return operational memory telemetry without raw memory fact text."""
        semantic_metrics = await conn.fetchrow(
            """
            SELECT
                COUNT(*)::int AS total_semantic,
                COUNT(*) FILTER (WHERE review_status = 'active')::int AS active_semantic,
                COUNT(*) FILTER (WHERE review_status = 'pending_review')::int AS pending_review,
                COUNT(*) FILTER (WHERE review_status = 'rejected')::int AS rejected,
                COUNT(*) FILTER (WHERE review_status = 'archived')::int AS archived,
                COUNT(*) FILTER (
                    WHERE created_at >= now() - INTERVAL '24 hours'
                )::int AS semantic_saves_24h,
                COUNT(*) FILTER (
                    WHERE created_at >= now() - INTERVAL '7 days'
                )::int AS semantic_saves_7d,
                COUNT(*) FILTER (
                    WHERE review_status = 'pending_review'
                      AND created_at >= now() - INTERVAL '24 hours'
                )::int AS review_required_24h
            FROM alpha_semantic_memory
            WHERE user_id = $1
            """,
            user_id,
        )
        source_rows = await conn.fetch(
            """
            SELECT
                COALESCE(NULLIF(provenance->>'source_surface', ''), source, 'unknown')
                    AS label,
                COUNT(*)::int AS count
            FROM alpha_semantic_memory
            WHERE user_id = $1
              AND created_at >= now() - INTERVAL '7 days'
            GROUP BY label
            ORDER BY count DESC, label ASC
            LIMIT 8
            """,
            user_id,
        )
        category_rows = await conn.fetch(
            """
            SELECT category AS label, COUNT(*)::int AS count
            FROM alpha_semantic_memory
            WHERE user_id = $1
              AND created_at >= now() - INTERVAL '7 days'
            GROUP BY category
            ORDER BY count DESC, category ASC
            LIMIT 8
            """,
            user_id,
        )
        recent_saves = await conn.fetch(
            """
            SELECT
                s.id::text,
                s.category,
                s.review_status,
                s.review_reason,
                s.created_at,
                s.updated_at,
                COALESCE(NULLIF(s.provenance->>'source_surface', ''), s.source, 'unknown')
                    AS source_surface,
                COALESCE(NULLIF(s.provenance->>'source_action', ''), 'unknown')
                    AS source_action,
                b.id::text AS buddy_event_id
            FROM alpha_semantic_memory s
            LEFT JOIN LATERAL (
                SELECT id
                FROM alpha_buddy_events
                WHERE payload->>'memory_id' = s.id::text
                ORDER BY created_at DESC
                LIMIT 1
            ) b ON true
            WHERE s.user_id = $1
            ORDER BY s.created_at DESC
            LIMIT $2
            """,
            user_id,
            recent_limit,
        )
        buddy_metrics = await conn.fetchrow(
            """
            SELECT
                COUNT(*)::int AS memory_buddy_events_7d,
                COUNT(*) FILTER (WHERE read = false)::int AS unread_memory_buddy_events,
                COUNT(*) FILTER (WHERE priority >= 3)::int AS high_priority_buddy_events
            FROM alpha_buddy_events
            WHERE user_id = $1
              AND created_at >= now() - INTERVAL '7 days'
              AND (
                source = 'semantic_memory_review'
                OR payload ? 'memory_id'
                OR title ILIKE '%memory%'
              )
            """,
            str(user_id),
        )
        recent_buddy_events = await conn.fetch(
            """
            SELECT
                id::text,
                event_type,
                title,
                priority,
                read,
                source,
                payload->>'memory_id' AS memory_id,
                created_at
            FROM alpha_buddy_events
            WHERE user_id = $1
              AND (
                source = 'semantic_memory_review'
                OR payload ? 'memory_id'
                OR title ILIKE '%memory%'
              )
            ORDER BY created_at DESC
            LIMIT $2
            """,
            str(user_id),
            recent_limit,
        )
        proposal_metrics = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE p.created_at >= now() - INTERVAL '7 days'
                )::int AS dream_proposals_7d,
                COUNT(*) FILTER (
                    WHERE p.executable
                      AND p.status IN ('pending_review', 'queued', 'approved')
                )::int AS dream_reviewed_writes_open,
                COUNT(*) FILTER (WHERE p.status = 'queued')::int
                    AS dream_proposals_queued,
                COUNT(*) FILTER (WHERE p.status = 'informational')::int
                    AS dream_informational_open,
                COUNT(*) FILTER (
                    WHERE p.executable
                      AND p.status = 'queued'
                      AND q.status = 'approved'
                )::int AS dream_approved_waiting_execution,
                COUNT(*) FILTER (WHERE p.status = 'executed')::int
                    AS dream_proposals_executed,
                COUNT(*) FILTER (WHERE p.status = 'reverted')::int
                    AS dream_proposals_reverted,
                COUNT(*) FILTER (
                    WHERE p.executable
                      AND p.status IN ('pending_review', 'queued', 'approved')
                      AND p.updated_at < now() - INTERVAL '48 hours'
                )::int AS stale_dream_reviewed_writes,
                COUNT(*) FILTER (
                    WHERE p.executable
                      AND p.status IN ('queued', 'approved')
                      AND (
                        p.approval_queue_id IS NULL
                        OR q.id IS NULL
                        OR q.status NOT IN ('pending', 'approved')
                        OR q.expires_at IS NULL
                        OR q.expires_at <= now()
                      )
                )::int AS dream_approval_mismatch_count,
                COUNT(*) FILTER (
                    WHERE p.status = 'executed'
                      AND l.proposal_id IS NULL
                )::int AS dream_executed_without_ledger
            FROM alpha_memory_consolidation_proposals p
            LEFT JOIN alpha_approval_queue q
              ON q.id = p.approval_queue_id
            LEFT JOIN alpha_memory_consolidation_execution_ledger l
              ON l.proposal_id = p.id
             AND l.status = 'executed'
            WHERE p.user_id = $1
            """,
            user_id,
        )
        recent_dream_proposals = await conn.fetch(
            """
            SELECT
                p.id::text AS proposal_id,
                p.proposed_action,
                p.executable,
                p.status,
                p.approval_queue_id::text,
                q.status AS approval_status,
                p.created_at,
                p.updated_at
            FROM alpha_memory_consolidation_proposals p
            LEFT JOIN alpha_approval_queue q
              ON q.id = p.approval_queue_id
            WHERE p.user_id = $1
            ORDER BY p.updated_at DESC
            LIMIT $2
            """,
            user_id,
            recent_limit,
        )
        return {
            "semantic_metrics": dict(semantic_metrics or {}),
            "source_surfaces_7d": [dict(row) for row in source_rows],
            "categories_7d": [dict(row) for row in category_rows],
            "recent_semantic_saves": [dict(row) for row in recent_saves],
            "buddy_metrics": dict(buddy_metrics or {}),
            "recent_buddy_events": [dict(row) for row in recent_buddy_events],
            "proposal_metrics": dict(proposal_metrics or {}),
            "recent_dream_proposals": [dict(row) for row in recent_dream_proposals],
        }


def _semantic_summary_row(row: asyncpg.Record) -> dict[str, Any]:
    payload = dict(row)
    payload["provenance"] = _json_object(payload.get("provenance"))
    return payload


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return {str(key): item for key, item in decoded.items()}
    return {}
