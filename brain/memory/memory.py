from __future__ import annotations

import asyncio
from uuid import UUID

import asyncpg
import re

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_memory")

SEMANTIC_CAP = 50
EPISODIC_LIMIT = 5
WORKING_LIMIT = 10
PROMOTION_SCORE_THRESHOLD = 0.7
PROMOTION_ACCESS_THRESHOLD = 3


class MemoryService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

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
        user_id: UUID,
        prompt: str,
        session_id: str,
        embedding: list[float],
    ) -> str:
        semantic, episodic, working = await asyncio.gather(
            self._get_semantic(user_id),
            self._get_episodic(user_id, embedding),
            self._get_working(session_id),
        )

        parts = []

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

    # ------------------------------------------------------------------
    # TIER 1 — SEMANTIC (always injected, full read, no search)
    # ------------------------------------------------------------------

    async def _get_semantic(self, user_id: UUID) -> list[dict]:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                str(user_id),
            )
            rows = await conn.fetch(
                """
                SELECT fact, category
                FROM alpha_semantic_memory
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                SEMANTIC_CAP,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # TIER 2 — EPISODIC (vector search, context-triggered)
    # ------------------------------------------------------------------

    async def _get_episodic(self, user_id: UUID, embedding: list[float]) -> list[dict]:
        """
        Weighted retrieval: Stanford Generative Agents pattern.
        score = 0.3 * recency + 0.4 * importance + 0.3 * relevance
        All factors normalized to [0, 1].
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                str(user_id),
            )
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

            # Bump access tracking on retrieved rows (fire and forget)
            if rows:
                ids = [r["id"] for r in rows]
                await conn.execute(
                    """
                    UPDATE alpha_conversation_memory
                    SET access_count = access_count + 1,
                        last_accessed_at = now()
                    WHERE id = ANY($1::uuid[])
                    """,
                    ids,
                )

        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # TIER 3 — WORKING (last N turns this session)
    # ------------------------------------------------------------------

    async def _get_working(self, session_id: str) -> list[dict]:
        async with self.pool.acquire() as conn:
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
        user_id: UUID,
        session_id: str,
        summary: str,
        role: str,
        embedding: list[float],
        persistent: bool = False,
    ) -> None:
        # Write gate — skip noise (Mem0 intelligent filtering pattern)
        importance = self._score_importance(summary)
        if importance <= 0.1:
            return

        tier = "episodic" if persistent else "working"
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                str(user_id),
            )
            await conn.execute(
                """
                INSERT INTO alpha_conversation_memory
                  (user_id, session_id, role, content, summary, memory_type,
                   embedding, tier, persistent, importance_score)
                VALUES ($1, $2, $3, $4, $5, $6, $7::vector, $8, $9, $10)
                """,
                str(user_id),
                session_id,
                role,
                summary,
                summary,
                role,
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
        user_id: UUID,
        fact: str,
        category: str,
    ) -> dict:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                str(user_id),
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM alpha_semantic_memory WHERE user_id = $1",
                user_id,
            )
            if count >= SEMANTIC_CAP:
                return {"error": f"Semantic memory cap ({SEMANTIC_CAP}) reached"}
            await conn.execute(
                """
                INSERT INTO alpha_semantic_memory
                  (user_id, fact, category, source)
                VALUES ($1, $2, $3, 'explicit')
                """,
                user_id,
                fact,
                category,
            )
        return {"saved": True, "fact": fact, "category": category}

    # ------------------------------------------------------------------
    # BUDDY NIGHTLY PROMOTION — called by buddy_agent
    # ------------------------------------------------------------------

    async def promote_to_semantic(self, user_id: UUID) -> dict:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                str(user_id),
            )
            cap_check = await conn.fetchval(
                "SELECT COUNT(*) FROM alpha_semantic_memory WHERE user_id = $1",
                user_id,
            )
            if cap_check >= SEMANTIC_CAP:
                return {"promoted": 0, "reason": "cap_reached"}

            candidates = await conn.fetch(
                """
                SELECT id, summary
                FROM alpha_conversation_memory
                WHERE user_id = $1
                  AND tier = 'episodic'
                  AND importance_score >= $2
                  AND access_count >= $3
                LIMIT $4
                """,
                str(user_id),
                PROMOTION_SCORE_THRESHOLD,
                PROMOTION_ACCESS_THRESHOLD,
                SEMANTIC_CAP - cap_check,
            )

            promoted = 0
            for row in candidates:
                await conn.execute(
                    """
                    INSERT INTO alpha_semantic_memory
                      (user_id, fact, category, source)
                    VALUES ($1, $2, 'project', 'promoted')
                    ON CONFLICT DO NOTHING
                    """,
                    user_id,
                    row["summary"],
                )
                promoted += 1

        return {"promoted": promoted, "user_id": str(user_id)}

    # ------------------------------------------------------------------
    # EVICTION — 24hr TTL on working tier (called nightly by Buddy)
    # ------------------------------------------------------------------

    async def evict_working(self) -> dict:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM alpha_conversation_memory
                WHERE tier = 'working'
                  AND created_at < now() - interval '24 hours'
                """
            )
        return {"evicted": result}
