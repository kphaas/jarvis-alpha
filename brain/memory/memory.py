import json
import sys
from typing import Optional

import httpx

from brain.core.config import OLLAMA_URL
from brain.db.session import get_db


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


async def _embed(text: str) -> list[float] | None:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": "all-minilm", "prompt": text},
            )
            r.raise_for_status()
            data = r.json()
            emb = data.get("embedding")
            if emb is None:
                return None
            return [float(x) for x in emb]
    except Exception:
        return None


def _row_to_memory(row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "persistent": row["persistent"],
    }


class MemoryService:
    async def store(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        workspace_id: Optional[str] = None,
        persistent: bool = False,
    ) -> None:
        try:
            embedding = await _embed(content)
            emb_param: Optional[str]
            if embedding is None:
                emb_param = None
            else:
                emb_param = _vector_literal(embedding)
            async with get_db(user_id) as db:
                await db.execute(
                    """
                    INSERT INTO alpha_conversation_memory
                      (user_id, session_id, role, content, embedding, workspace_id, persistent)
                    VALUES ($1, $2, $3, $4, $5::vector, $6, $7)
                    """,
                    user_id,
                    session_id,
                    role,
                    content,
                    emb_param,
                    workspace_id,
                    persistent,
                )
        except Exception as e:
            print(f"MemoryService.store error: {e}", file=sys.stderr)

    async def recall(
        self,
        user_id: str,
        session_id: str,
        query: str,
        workspace_id: Optional[str] = None,
        limit: int = 5,
    ) -> list[dict]:
        try:
            phase1: list = []
            query_embedding = await _embed(query)

            # Phase 1 — workspace memory (if workspace_id provided)
            if workspace_id is not None:
                async with get_db(user_id) as db:
                    if query_embedding is not None:
                        rows = await db.fetch(
                            """
                            SELECT id, role, content, persistent,
                                   embedding <=> $1::vector AS distance
                            FROM alpha_conversation_memory
                            WHERE user_id = $2 AND workspace_id = $3
                            ORDER BY distance ASC
                            LIMIT $4
                            """,
                            _vector_literal(query_embedding),
                            user_id,
                            workspace_id,
                            limit,
                        )
                    else:
                        rows = await db.fetch(
                            """
                            SELECT id, role, content, persistent
                            FROM alpha_conversation_memory
                            WHERE user_id = $1 AND workspace_id = $2
                            ORDER BY created_at DESC
                            LIMIT $3
                            """,
                            user_id,
                            workspace_id,
                            limit,
                        )
                    phase1 = list(rows)

                if len(phase1) >= 3:
                    return [_row_to_memory(r) for r in phase1[:limit]]

            # Phase 2 — Brain global fallback (workspace results < 3)
            async with get_db(user_id) as db:
                if query_embedding is not None:
                    rows2 = await db.fetch(
                        """
                        SELECT id, role, content, persistent,
                               embedding <=> $1::vector AS distance
                        FROM alpha_conversation_memory
                        WHERE user_id = $2 AND workspace_id IS NULL
                        ORDER BY distance ASC
                        LIMIT $3
                        """,
                        _vector_literal(query_embedding),
                        user_id,
                        limit,
                    )
                else:
                    rows2 = await db.fetch(
                        """
                        SELECT id, role, content, persistent
                        FROM alpha_conversation_memory
                        WHERE user_id = $1 AND workspace_id IS NULL
                        ORDER BY created_at DESC
                        LIMIT $2
                        """,
                        user_id,
                        limit,
                    )

            phase2 = list(rows2)
            seen: set = set()
            merged: list[dict] = []
            for r in phase1 + phase2:
                rid = r["id"]
                if rid in seen:
                    continue
                seen.add(rid)
                merged.append(_row_to_memory(r))
                if len(merged) >= limit:
                    break
            return merged
        except Exception:
            return []

    async def clear_session(self, user_id: str, session_id: str) -> None:
        try:
            async with get_db(user_id) as db:
                await db.execute(
                    """
                    DELETE FROM alpha_conversation_memory
                    WHERE user_id = $1 AND session_id = $2 AND persistent = false
                    """,
                    user_id,
                    session_id,
                )
        except Exception as e:
            print(f"MemoryService.clear_session error: {e}", file=sys.stderr)

    async def build_context(
        self,
        user_id: str,
        session_id: str,
        query: str,
        workspace_id: Optional[str] = None,
    ) -> str:
        memories = await self.recall(user_id, session_id, query, workspace_id)
        if not memories:
            return ""
        return "\n".join(
            [f"{m['role'].upper()}: {m['content']}" for m in memories]
        )
