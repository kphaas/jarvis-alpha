from __future__ import annotations

import json
import re
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

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

    async def update_semantic(
        self,
        conn: asyncpg.Connection,
        user_id: UUID,
        memory_id: UUID,
        fact: str,
        category: str,
        updated_by: str,
    ) -> dict:
        review_status = (
            "pending_review" if category in {"health", "child_profile"} else "active"
        )
        review_reason = (
            "sensitive_category" if review_status == "pending_review" else None
        )
        payload = await conn.fetchrow(
            """
            UPDATE public.alpha_semantic_memory
               SET fact = $3,
                   category = $4,
                   review_status = $5,
                   review_reason = $6,
                   reviewed_at = NULL,
                   reviewed_by = NULL,
                   updated_at = NOW(),
                   provenance = COALESCE(provenance, '{}'::jsonb) || jsonb_build_object(
                       'last_user_edit_action', 'correct',
                       'last_user_edit_by', $7,
                       'last_user_edit_at', NOW()::text,
                       'review_lane', CASE WHEN $5 = 'pending_review' THEN 'high_visibility' ELSE 'standard' END
                   )
             WHERE user_id = $1
               AND id = $2
               AND COALESCE(review_status, 'active') <> 'archived'
             RETURNING id::text,
                       fact,
                       category,
                       source,
                       provenance,
                       review_status,
                       review_reason,
                       reviewed_at,
                       reviewed_by,
                       created_at,
                       updated_at
            """,
            user_id,
            memory_id,
            fact,
            category,
            review_status,
            review_reason,
            updated_by,
        )
        if payload is None:
            return {"status": "not_found", "memory_id": str(memory_id)}
        result = dict(payload)
        result["status"] = "updated"
        result["review_required"] = review_status == "pending_review"
        if review_status == "pending_review":
            result["buddy_event_id"] = await self._record_semantic_review_event(
                conn=conn,
                user_id=user_id,
                memory_id=memory_id,
                category=category,
                review_status=review_status,
                review_reason=review_reason,
            )
        return result

    async def _record_semantic_review_event(
        self,
        *,
        conn: asyncpg.Connection,
        user_id: UUID,
        memory_id: UUID,
        category: str,
        review_status: str,
        review_reason: str | None,
    ) -> str | None:
        try:
            event_id = await conn.fetchval(
                """
                SELECT public.record_buddy_event(
                    $1,
                    'alert',
                    'Memory review needed',
                    'A health or child-profile memory was edited and needs review.',
                    3,
                    'semantic_memory_review',
                    $2::jsonb
                )
                """,
                str(user_id),
                json.dumps(
                    {
                        "memory_id": str(memory_id),
                        "category": category,
                        "review_status": review_status,
                        "review_reason": review_reason,
                        "source_surface": "memory_api",
                        "contains_fact": False,
                    },
                    sort_keys=True,
                ),
            )
        except Exception as exc:
            logger.warning(
                "semantic memory review event failed during update: %s",
                exc,
                extra={
                    "event": "MEMORY_SEMANTIC_UPDATE_REVIEW_EVENT_FAILED",
                    "user_id": str(user_id),
                    "memory_id": str(memory_id),
                },
            )
            return None
        return str(event_id) if event_id else None

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
            WITH memory_events AS (
                SELECT
                    priority,
                    read,
                    source,
                    title,
                    COALESCE(payload, '{}'::jsonb) AS payload
                FROM alpha_buddy_events
                WHERE user_id = $1
                  AND created_at >= now() - INTERVAL '7 days'
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
                    OR (priority >= 3 AND title ILIKE '%memory%')
                  )
            ),
            actionable AS (
                SELECT *,
                    read = false
                    AND NOT (
                        payload ? 'memory_suppression'
                        OR payload ? 'memory_admin_suppression'
                    )
                    AND (
                        source IN (
                            'semantic_memory_review',
                            'memory_observability_monitor'
                        )
                        OR payload ? 'memory_id'
                        OR payload ? 'proposal_id'
                        OR priority >= 3
                    ) AS actionable_unread
                FROM memory_events
            )
            SELECT
                COUNT(*)::int AS memory_buddy_events_7d,
                COUNT(*) FILTER (WHERE actionable_unread)::int
                    AS unread_memory_buddy_events,
                COUNT(*) FILTER (
                    WHERE actionable_unread AND priority >= 3
                )::int AS high_priority_buddy_events
            FROM actionable
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
                source IN (
                    'semantic_memory_review',
                    'memory_observability_monitor',
                    'memory_consolidation',
                    'spark_memory_grounding'
                )
                OR COALESCE(payload, '{}'::jsonb) ? 'memory_id'
                OR COALESCE(payload, '{}'::jsonb) ? 'proposal_id'
                OR COALESCE(payload, '{}'::jsonb) ? 'fingerprint'
                OR (priority >= 3 AND title ILIKE '%memory%')
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
                q.expires_at AS approval_expires_at,
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

    async def mark_memory_buddy_events_read(
        self,
        conn: asyncpg.Connection,
        *,
        user_id: UUID,
        event_ids: list[UUID] | None = None,
        high_priority_only: bool = False,
        marked_by: str = "unknown",
    ) -> dict[str, Any]:
        """Mark memory-related Buddy events read for one RLS-visible user."""

        event_id_values = [str(event_id) for event_id in event_ids or []] or None
        rows = await conn.fetch(
            """
            WITH target AS (
                SELECT id
                FROM public.alpha_buddy_events
                WHERE user_id = $1
                  AND read = false
                  AND ($2::uuid[] IS NULL OR id = ANY($2::uuid[]))
                  AND ($3::boolean = false OR priority >= 3)
                  AND (
                    source = 'semantic_memory_review'
                    OR source = 'memory_observability_monitor'
                    OR payload ? 'memory_id'
                    OR title ILIKE '%memory%'
                  )
            )
            UPDATE public.alpha_buddy_events e
               SET read = true,
                   payload = jsonb_set(
                       COALESCE(e.payload, '{}'::jsonb),
                       '{memory_read}',
                       jsonb_build_object(
                           'marked_by', $4,
                           'marked_at', now()::text
                       ),
                       true
                   )
              FROM target
             WHERE e.id = target.id
            RETURNING e.id::text
            """,
            str(user_id),
            event_id_values,
            high_priority_only,
            marked_by,
        )
        marked_ids = [str(row["id"]) for row in rows]
        return {
            "status": "marked_read",
            "marked_count": len(marked_ids),
            "marked_ids": marked_ids,
        }

    async def admin_mark_memory_buddy_events_read(
        self,
        conn: asyncpg.Connection,
        *,
        event_ids: list[UUID] | None = None,
        high_priority_only: bool = False,
        marked_by: str = "unknown",
    ) -> dict[str, Any]:
        """Mark memory-related Buddy events read across all principals."""

        event_id_values = [str(event_id) for event_id in event_ids or []] or None
        rows = await conn.fetch(
            """
            WITH target AS (
                SELECT id
                FROM public.alpha_buddy_events
                WHERE read = false
                  AND ($1::uuid[] IS NULL OR id = ANY($1::uuid[]))
                  AND ($2::boolean = false OR priority >= 3)
                  AND (
                    source = 'semantic_memory_review'
                    OR source = 'memory_observability_monitor'
                    OR payload ? 'memory_id'
                    OR title ILIKE '%memory%'
                  )
            )
            UPDATE public.alpha_buddy_events e
               SET read = true,
                   payload = jsonb_set(
                       COALESCE(e.payload, '{}'::jsonb),
                       '{memory_admin_read}',
                       jsonb_build_object(
                           'marked_by', $3::text,
                           'marked_at', now()::text
                       ),
                       true
                   )
              FROM target
             WHERE e.id = target.id
            RETURNING e.id::text
            """,
            event_id_values,
            high_priority_only,
            marked_by,
        )
        marked_ids = [str(row["id"]) for row in rows]
        return {
            "status": "marked_read",
            "marked_count": len(marked_ids),
            "marked_ids": marked_ids,
        }

    async def suppress_duplicate_memory_buddy_events(
        self,
        conn: asyncpg.Connection,
        *,
        user_id: UUID,
        window_hours: int = 168,
        high_priority_only: bool = False,
        suppressed_by: str = "unknown",
    ) -> dict[str, Any]:
        """Mark duplicate unread memory Buddy events read, keeping the newest."""

        rows = await conn.fetch(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            COALESCE(source, ''),
                            COALESCE(payload->>'memory_id', ''),
                            COALESCE(payload->>'proposal_id', ''),
                            event_type,
                            title
                        ORDER BY created_at DESC, id DESC
                    ) AS row_rank
                FROM public.alpha_buddy_events
                WHERE user_id = $1
                  AND read = false
                  AND created_at >= now() - make_interval(hours => $2::int)
                  AND ($3::boolean = false OR priority >= 3)
                  AND (
                    source = 'semantic_memory_review'
                    OR source = 'memory_observability_monitor'
                    OR payload ? 'memory_id'
                    OR title ILIKE '%memory%'
                  )
            )
            UPDATE public.alpha_buddy_events e
               SET read = true,
                   payload = jsonb_set(
                       COALESCE(e.payload, '{}'::jsonb),
                       '{memory_suppression}',
                       jsonb_build_object(
                           'reason', 'duplicate',
                           'suppressed_by', $4,
                           'suppressed_at', now()::text
                       ),
                       true
                   )
              FROM ranked
             WHERE e.id = ranked.id
               AND ranked.row_rank > 1
            RETURNING e.id::text
            """,
            str(user_id),
            window_hours,
            high_priority_only,
            suppressed_by,
        )
        suppressed_ids = [str(row["id"]) for row in rows]
        return {
            "status": "duplicates_suppressed",
            "suppressed_count": len(suppressed_ids),
            "suppressed_ids": suppressed_ids,
            "window_hours": window_hours,
        }

    async def admin_suppress_duplicate_memory_buddy_events(
        self,
        conn: asyncpg.Connection,
        *,
        window_hours: int = 168,
        high_priority_only: bool = False,
        suppressed_by: str = "unknown",
    ) -> dict[str, Any]:
        """Mark duplicate unread memory Buddy events read across all principals."""

        rows = await conn.fetch(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            user_id,
                            COALESCE(source, ''),
                            COALESCE(payload->>'memory_id', ''),
                            COALESCE(payload->>'proposal_id', ''),
                            event_type,
                            title
                        ORDER BY created_at DESC, id DESC
                    ) AS row_rank
                FROM public.alpha_buddy_events
                WHERE read = false
                  AND created_at >= now() - make_interval(hours => $1::int)
                  AND ($2::boolean = false OR priority >= 3)
                  AND (
                    source = 'semantic_memory_review'
                    OR source = 'memory_observability_monitor'
                    OR payload ? 'memory_id'
                    OR title ILIKE '%memory%'
                  )
            )
            UPDATE public.alpha_buddy_events e
               SET read = true,
                   payload = jsonb_set(
                       COALESCE(e.payload, '{}'::jsonb),
                       '{memory_admin_suppression}',
                       jsonb_build_object(
                           'reason', 'duplicate',
                           'suppressed_by', $3::text,
                           'suppressed_at', now()::text
                       ),
                       true
                   )
              FROM ranked
             WHERE e.id = ranked.id
               AND ranked.row_rank > 1
            RETURNING e.id::text
            """,
            window_hours,
            high_priority_only,
            suppressed_by,
        )
        suppressed_ids = [str(row["id"]) for row in rows]
        return {
            "status": "duplicates_suppressed",
            "suppressed_count": len(suppressed_ids),
            "suppressed_ids": suppressed_ids,
            "window_hours": window_hours,
        }

    async def admin_inventory(
        self,
        conn: asyncpg.Connection,
        *,
        limit: int = 100,
    ) -> dict:
        """Return per-principal memory inventory for operator review."""
        identity_rows = await conn.fetch(
            """
            WITH identities AS (
                SELECT
                    p.id::text AS profile_id,
                    p.display_name::text AS display_name,
                    p.role::text AS role,
                    p.child_age::int AS child_age
                FROM public.alpha_profiles p
                WHERE COALESCE(p.active, true) = true
                UNION
                SELECT
                    u.id::text AS profile_id,
                    split_part(u.email::text, '@', 1) AS display_name,
                    u.role::text AS role,
                    u.child_age::int AS child_age
                FROM public.alpha_users u
            )
            SELECT DISTINCT ON (profile_id)
                profile_id,
                COALESCE(NULLIF(display_name, ''), profile_id) AS display_name,
                COALESCE(NULLIF(role, ''), 'user') AS role,
                child_age
            FROM identities
            WHERE profile_id IS NOT NULL AND profile_id <> ''
            ORDER BY profile_id, display_name
            """,
        )
        principal_rows = await conn.fetch(
            """
            WITH principals AS (
                SELECT user_id::text AS principal_id
                FROM public.alpha_semantic_memory
                UNION
                SELECT user_id::text AS principal_id
                FROM public.alpha_conversation_memory
                UNION
                SELECT user_id::text AS principal_id
                FROM public.alpha_memory_consolidation_proposals
            ),
            semantic_counts AS (
                SELECT
                    user_id::text AS principal_id,
                    COUNT(*)::int AS semantic_count,
                    COUNT(*) FILTER (
                        WHERE review_status = 'pending_review'
                    )::int AS pending_review,
                    MAX(updated_at) AS semantic_last_at
                FROM public.alpha_semantic_memory
                GROUP BY user_id
            ),
            conversation_counts AS (
                SELECT
                    user_id::text AS principal_id,
                    COUNT(*) FILTER (WHERE tier = 'working')::int AS working_count,
                    COUNT(*) FILTER (WHERE tier = 'episodic')::int AS episodic_count,
                    MAX(created_at) AS conversation_last_at
                FROM public.alpha_conversation_memory
                GROUP BY user_id
            ),
            proposal_counts AS (
                SELECT
                    p.user_id::text AS principal_id,
                    COUNT(*) FILTER (
                        WHERE p.executable
                          AND p.status IN ('pending_review', 'queued', 'approved')
                    )::int AS dream_reviewed_writes_open,
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
                    MAX(p.updated_at) AS proposal_last_at
                FROM public.alpha_memory_consolidation_proposals p
                LEFT JOIN public.alpha_approval_queue q
                  ON q.id = p.approval_queue_id
                GROUP BY p.user_id
            )
            SELECT
                principals.principal_id,
                COALESCE(semantic_counts.semantic_count, 0)::int AS semantic_count,
                COALESCE(semantic_counts.pending_review, 0)::int AS pending_review,
                COALESCE(conversation_counts.working_count, 0)::int AS working_count,
                COALESCE(conversation_counts.episodic_count, 0)::int AS episodic_count,
                COALESCE(proposal_counts.dream_reviewed_writes_open, 0)::int
                    AS dream_reviewed_writes_open,
                COALESCE(proposal_counts.dream_approval_mismatch_count, 0)::int
                    AS dream_approval_mismatch_count,
                GREATEST(
                    semantic_counts.semantic_last_at,
                    conversation_counts.conversation_last_at,
                    proposal_counts.proposal_last_at
                ) AS last_activity_at
            FROM principals
            LEFT JOIN semantic_counts USING (principal_id)
            LEFT JOIN conversation_counts USING (principal_id)
            LEFT JOIN proposal_counts USING (principal_id)
            ORDER BY last_activity_at DESC NULLS LAST, principal_id ASC
            LIMIT $1
            """,
            limit,
        )
        health = await self.admin_health(conn)
        inventory = _merge_admin_inventory(identity_rows, principal_rows, limit=limit)
        inventory["health"] = health
        return inventory

    async def admin_health(self, conn: asyncpg.Connection) -> dict[str, Any]:
        """Return aggregate memory health metrics for operator dashboards."""

        row = await conn.fetchrow(
            """
            WITH principals AS (
                SELECT p.id::text AS principal_id
                FROM public.alpha_profiles p
                WHERE COALESCE(p.active, true) = true
                UNION
                SELECT u.id::text AS principal_id
                FROM public.alpha_users u
                UNION
                SELECT user_id::text AS principal_id
                FROM public.alpha_semantic_memory
                UNION
                SELECT user_id::text AS principal_id
                FROM public.alpha_conversation_memory
                UNION
                SELECT user_id::text AS principal_id
                FROM public.alpha_memory_consolidation_proposals
            ),
            semantic AS (
                SELECT
                    COUNT(*)::int AS total_semantic,
                    COUNT(*) FILTER (
                        WHERE review_status = 'pending_review'
                    )::int AS semantic_review_count,
                    MAX(created_at) AS last_semantic_write_at,
                    MAX(reviewed_at) FILTER (
                        WHERE reviewed_at IS NOT NULL
                    ) AS last_semantic_review_at
                FROM public.alpha_semantic_memory
            ),
            conversation AS (
                SELECT
                    COUNT(*) FILTER (WHERE tier = 'working')::int AS total_working,
                    COUNT(*) FILTER (WHERE tier = 'episodic')::int AS total_episodic,
                    MAX(created_at) FILTER (
                        WHERE tier = 'working'
                    ) AS last_working_memory_at,
                    MAX(created_at) FILTER (
                        WHERE tier = 'episodic'
                    ) AS last_episodic_memory_at
                FROM public.alpha_conversation_memory
            ),
            proposals AS (
                SELECT
                    COUNT(*) FILTER (
                        WHERE p.executable
                          AND p.status IN ('pending_review', 'queued', 'approved')
                    )::int AS dream_reviewed_writes_open,
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
                        WHERE p.executable
                          AND p.status IN ('pending_review', 'queued', 'approved')
                          AND p.updated_at < now() - INTERVAL '48 hours'
                    )::int AS stale_dream_reviewed_writes,
                    COUNT(*) FILTER (
                        WHERE p.executable
                          AND p.status = 'queued'
                          AND q.status = 'approved'
                    )::int AS dream_approved_waiting_execution,
                    MAX(created_at) AS last_dream_extraction_at,
                    MAX(updated_at) AS last_dream_proposal_update_at
                FROM public.alpha_memory_consolidation_proposals p
                LEFT JOIN public.alpha_approval_queue q
                  ON q.id = p.approval_queue_id
            ),
            buddy_events AS (
                SELECT
                    priority,
                    read,
                    source,
                    title,
                    created_at,
                    COALESCE(payload, '{}'::jsonb) AS payload
                FROM public.alpha_buddy_events
                WHERE source IN (
                        'semantic_memory_review',
                        'memory_observability_monitor',
                        'memory_consolidation',
                        'spark_memory_grounding'
                    )
                   OR COALESCE(payload, '{}'::jsonb) ? 'memory_id'
                   OR COALESCE(payload, '{}'::jsonb) ? 'proposal_id'
                   OR COALESCE(payload, '{}'::jsonb) ? 'fingerprint'
                   OR (priority >= 3 AND title ILIKE '%memory%')
            ),
            buddy_actionable AS (
                SELECT *,
                    read = false
                    AND created_at >= now() - INTERVAL '7 days'
                    AND NOT (
                        payload ? 'memory_suppression'
                        OR payload ? 'memory_admin_suppression'
                    )
                    AND (
                        source IN (
                            'semantic_memory_review',
                            'memory_observability_monitor'
                        )
                        OR payload ? 'memory_id'
                        OR payload ? 'proposal_id'
                        OR priority >= 3
                    ) AS actionable_unread
                FROM buddy_events
            ),
            buddy AS (
                SELECT
                    COUNT(*) FILTER (WHERE actionable_unread)::int
                        AS unread_memory_buddy_events,
                    COUNT(*) FILTER (
                        WHERE actionable_unread AND priority >= 3
                    )::int
                        AS high_priority_buddy_events,
                    MAX(created_at) AS last_memory_alert_at
                FROM buddy_actionable
            )
            SELECT
                (SELECT COUNT(*)::int FROM principals) AS principal_count,
                semantic.total_semantic,
                semantic.semantic_review_count,
                semantic.last_semantic_write_at,
                semantic.last_semantic_review_at,
                conversation.total_working,
                conversation.total_episodic,
                conversation.last_working_memory_at,
                conversation.last_episodic_memory_at,
                proposals.dream_reviewed_writes_open,
                proposals.dream_approval_mismatch_count,
                proposals.stale_dream_reviewed_writes,
                proposals.dream_approved_waiting_execution,
                proposals.last_dream_extraction_at,
                proposals.last_dream_proposal_update_at,
                buddy.unread_memory_buddy_events,
                buddy.high_priority_buddy_events,
                buddy.last_memory_alert_at,
                GREATEST(
                    semantic.last_semantic_write_at,
                    conversation.last_working_memory_at,
                    conversation.last_episodic_memory_at,
                    proposals.last_dream_proposal_update_at,
                    buddy.last_memory_alert_at
                ) AS last_memory_activity_at
            FROM semantic, conversation, proposals, buddy
            """,
        )
        return dict(row or {})

    async def admin_dream_proposals(
        self,
        conn: asyncpg.Connection,
        *,
        state: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return Dream proposal queue rows without raw proposal evidence."""

        rows = await conn.fetch(
            """
            WITH identities AS (
                SELECT
                    p.id::text AS profile_id,
                    p.display_name::text AS display_name,
                    p.role::text AS role
                FROM public.alpha_profiles p
                WHERE COALESCE(p.active, true) = true
                UNION
                SELECT
                    u.id::text AS profile_id,
                    split_part(u.email::text, '@', 1) AS display_name,
                    u.role::text AS role
                FROM public.alpha_users u
            )
            SELECT
                p.user_id::text AS principal_id,
                COALESCE(
                    NULLIF(i.display_name, ''),
                    p.user_id::text
                ) AS display_name,
                COALESCE(NULLIF(i.role, ''), 'unknown') AS role,
                p.id::text AS proposal_id,
                p.proposed_action,
                p.executable,
                p.status,
                p.approval_queue_id::text,
                q.status AS approval_status,
                q.expires_at AS approval_expires_at,
                p.created_at,
                p.updated_at
            FROM public.alpha_memory_consolidation_proposals p
            LEFT JOIN public.alpha_approval_queue q
              ON q.id = p.approval_queue_id
            LEFT JOIN identities i
              ON i.profile_id = p.user_id::text
            WHERE (
                $1 = 'all'
                OR (
                    p.executable
                    AND p.status IN ('pending_review', 'queued', 'approved')
                )
            )
            ORDER BY
                CASE
                    WHEN p.executable
                     AND p.status IN ('pending_review', 'queued', 'approved')
                    THEN 0
                    ELSE 1
                END,
                p.updated_at DESC
            LIMIT $2
            """,
            state,
            limit,
        )
        return [dict(row) for row in rows]

    async def admin_user_memory(
        self,
        conn: asyncpg.Connection,
        *,
        principal_id: UUID,
        principal_aliases: list[str],
        semantic_limit: int = 100,
        working_limit: int = 50,
        proposal_limit: int = 25,
    ) -> dict:
        """Return bounded raw memory rows for one operator-selected principal."""
        semantic_rows = await conn.fetch(
            """
            SELECT id::text, fact, category, source, provenance,
                   review_status, review_reason, reviewed_at, reviewed_by,
                   created_at, updated_at
            FROM public.alpha_semantic_memory
            WHERE user_id = $1
              AND COALESCE(review_status, 'active') <> 'archived'
            ORDER BY updated_at DESC, created_at DESC
            LIMIT $2
            """,
            principal_id,
            semantic_limit,
        )
        semantic_metrics = await conn.fetchrow(
            """
            SELECT
                COUNT(*)::int AS semantic_count,
                COUNT(*) FILTER (WHERE review_status = 'pending_review')::int
                    AS semantic_review_count
            FROM public.alpha_semantic_memory
            WHERE user_id = $1
              AND COALESCE(review_status, 'active') <> 'archived'
            """,
            principal_id,
        )
        conversation_counts = await conn.fetch(
            """
            SELECT tier, COUNT(*)::int AS count
            FROM public.alpha_conversation_memory
            WHERE user_id = ANY($1::text[])
            GROUP BY tier
            """,
            principal_aliases,
        )
        working_rows = await conn.fetch(
            """
            SELECT id::text, session_id, summary, memory_type AS role,
                   importance_score, created_at
            FROM public.alpha_conversation_memory
            WHERE user_id = ANY($1::text[])
              AND tier = 'working'
            ORDER BY created_at DESC
            LIMIT $2
            """,
            principal_aliases,
            working_limit,
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
                q.expires_at AS approval_expires_at,
                p.created_at,
                p.updated_at
            FROM public.alpha_memory_consolidation_proposals p
            LEFT JOIN public.alpha_approval_queue q
              ON q.id = p.approval_queue_id
            WHERE p.user_id = $1
            ORDER BY p.updated_at DESC
            LIMIT $2
            """,
            principal_id,
            proposal_limit,
        )
        tier_counts = {
            str(row["tier"]): int(row["count"]) for row in conversation_counts
        }
        return {
            "semantic_count": int((semantic_metrics or {}).get("semantic_count") or 0),
            "semantic_review_count": int(
                (semantic_metrics or {}).get("semantic_review_count") or 0
            ),
            "episodic_count": tier_counts.get("episodic", 0),
            "working_count": tier_counts.get("working", 0),
            "semantic": [_semantic_summary_row(row) for row in semantic_rows],
            "working": [dict(row) for row in working_rows],
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


def _merge_admin_inventory(
    identity_rows: list[asyncpg.Record],
    principal_rows: list[asyncpg.Record],
    *,
    limit: int,
) -> dict:
    identities: dict[str, dict[str, Any]] = {}
    alias_to_key: dict[str, str] = {}
    for row in identity_rows:
        profile_id = str(row["profile_id"])
        canonical_id = _canonical_principal_id(profile_id)
        identity = {
            "principal_id": canonical_id,
            "profile_id": profile_id,
            "display_name": str(row["display_name"] or profile_id),
            "role": str(row["role"] or "user"),
            "child_age": row["child_age"],
            "aliases": sorted({profile_id, canonical_id}),
        }
        identities[canonical_id] = identity
        alias_to_key[profile_id] = canonical_id
        alias_to_key[canonical_id] = canonical_id

    entries: dict[str, dict[str, Any]] = {}
    for canonical_id, identity in identities.items():
        entries[canonical_id] = {
            **identity,
            "semantic_count": 0,
            "semantic_review_count": 0,
            "working_count": 0,
            "episodic_count": 0,
            "dream_reviewed_writes_open": 0,
            "dream_approval_mismatch_count": 0,
            "last_activity_at": None,
        }

    for row in principal_rows:
        principal_id = str(row["principal_id"])
        key = alias_to_key.get(principal_id, principal_id)
        if key not in entries:
            entries[key] = {
                "principal_id": principal_id,
                "profile_id": None,
                "display_name": principal_id,
                "role": "unknown",
                "child_age": None,
                "aliases": [principal_id],
                "semantic_count": 0,
                "semantic_review_count": 0,
                "working_count": 0,
                "episodic_count": 0,
                "dream_reviewed_writes_open": 0,
                "dream_approval_mismatch_count": 0,
                "last_activity_at": None,
            }
        entry = entries[key]
        entry["semantic_count"] += int(row["semantic_count"] or 0)
        entry["semantic_review_count"] += int(row["pending_review"] or 0)
        entry["working_count"] += int(row["working_count"] or 0)
        entry["episodic_count"] += int(row["episodic_count"] or 0)
        entry["dream_reviewed_writes_open"] += int(
            row["dream_reviewed_writes_open"] or 0
        )
        entry["dream_approval_mismatch_count"] += int(
            row["dream_approval_mismatch_count"] or 0
        )
        entry["last_activity_at"] = _max_datetime(
            entry["last_activity_at"],
            row["last_activity_at"],
        )

    items = sorted(
        entries.values(),
        key=lambda item: (
            item["last_activity_at"] is not None,
            str(item["last_activity_at"] or ""),
            item["display_name"],
        ),
        reverse=True,
    )
    return {"users": items[:limit]}


def _canonical_principal_id(profile_id: str) -> str:
    try:
        return str(UUID(profile_id))
    except ValueError:
        return str(uuid5(NAMESPACE_DNS, profile_id))


def _max_datetime(left: object, right: object) -> object:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)
