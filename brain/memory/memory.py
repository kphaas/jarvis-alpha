from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg

SEMANTIC_CAP = 50
EPISODIC_LIMIT = 5
WORKING_LIMIT = 10
PROMOTION_SCORE_THRESHOLD = 0.7
PROMOTION_ACCESS_THRESHOLD = 3


class MemoryService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

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
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                str(user_id),
            )
            rows = await conn.fetch(
                """
                SELECT id, summary, importance_score
                FROM alpha_conversation_memory
                WHERE user_id = $1
                  AND tier = 'episodic'
                ORDER BY embedding <=> $2::vector
                LIMIT $3
                """,
                user_id,
                embedding,
                EPISODIC_LIMIT,
            )
            if rows:
                ids = [r["id"] for r in rows]
                await conn.execute(
                    """
                    UPDATE alpha_conversation_memory
                    SET access_count = access_count + 1,
                        last_accessed_at = now()
                    WHERE id = ANY($1)
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
        tier = "episodic" if persistent else "working"
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                str(user_id),
            )
            await conn.execute(
                """
                INSERT INTO alpha_conversation_memory
                  (user_id, session_id, summary, memory_type,
                   embedding, tier, persistent)
                VALUES ($1, $2, $3, $4, $5::vector, $6, $7)
                """,
                user_id,
                session_id,
                summary,
                role,
                embedding,
                tier,
                persistent,
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
                user_id,
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
