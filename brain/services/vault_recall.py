"""Vault document recall helpers for Ask and document search routes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from brain.core.config import OLLAMA_URL
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

VAULT_EMBED_MODEL = "all-minilm"
MAX_QUERY_CHARS = 500
MAX_EXCERPT_CHARS = 700
MAX_CONTEXT_CHARS = 3600
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MIN_VECTOR_SCORE = 0.2
TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+#/-]{1,80}")


@dataclass(frozen=True, slots=True)
class VaultSearchMatch:
    document_id: str
    filename: str
    classification: str
    content_type: str
    storage_tier: str
    status: str
    chunk_index: int
    excerpt: str
    score: float
    vector_score: float | None
    text_rank: float
    created_at: str | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "classification": self.classification,
            "content_type": self.content_type,
            "storage_tier": self.storage_tier,
            "status": self.status,
            "chunk_index": self.chunk_index,
            "excerpt": self.excerpt,
            "score": round(self.score, 6),
            "vector_score": None
            if self.vector_score is None
            else round(self.vector_score, 6),
            "text_rank": round(self.text_rank, 6),
            "created_at": self.created_at,
        }


def normalize_vault_query(query: str) -> str:
    return " ".join((query or "").split())[:MAX_QUERY_CHARS]


def _query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for match in TERM_RE.finditer(query.casefold()):
        term = match.group(0)
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= 8:
            break
    return terms


def _like_patterns(query: str) -> list[str]:
    return [f"%{term}%" for term in _query_terms(query)] or [f"%{query.casefold()}%"]


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


async def embed_vault_query(query: str) -> list[float] | None:
    normalized = normalize_vault_query(query)
    if not normalized:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": VAULT_EMBED_MODEL, "prompt": normalized},
            )
            if response.status_code != 200:
                return None
            data = response.json()
            embedding = data.get("embedding")
            if not isinstance(embedding, list):
                return None
            return [float(value) for value in embedding]
    except Exception as exc:
        logger.warning("vault query embedding failed: %s", exc)
        return None


async def search_vault_chunks(
    conn: Any,
    *,
    query: str,
    limit: int = DEFAULT_LIMIT,
    embedding: list[float] | None = None,
) -> list[VaultSearchMatch]:
    normalized = normalize_vault_query(query)
    if not normalized:
        return []

    bounded_limit = min(max(1, int(limit)), MAX_LIMIT)
    patterns = _like_patterns(normalized)
    if embedding:
        rows = await conn.fetch(
            """
            WITH ranked AS (
                SELECT
                    vd.id AS document_id,
                    vd.filename,
                    vd.classification,
                    vd.content_type,
                    vd.storage_tier,
                    vd.status,
                    vc.chunk_index,
                    vc.content,
                    vc.created_at,
                    CASE
                      WHEN vc.embedding IS NULL THEN NULL
                      ELSE 1 - (vc.embedding <=> $2::vector)
                    END AS vector_score,
                    ts_rank_cd(
                        to_tsvector('simple', vc.content || ' ' || vd.filename),
                        websearch_to_tsquery('simple', $3)
                    ) AS text_rank
                FROM vault_chunks vc
                JOIN vault_documents vd ON vd.id = vc.document_id
            )
            SELECT
                document_id,
                filename,
                classification,
                content_type,
                storage_tier,
                status,
                chunk_index,
                content,
                created_at,
                vector_score,
                text_rank,
                (
                    COALESCE(vector_score, 0) * 0.75
                  + COALESCE(text_rank, 0) * 0.25
                ) AS score
            FROM ranked
            WHERE COALESCE(vector_score, 0) >= $4
               OR COALESCE(text_rank, 0) > 0
               OR content ILIKE ANY($5::text[])
               OR filename ILIKE ANY($5::text[])
            ORDER BY score DESC, created_at DESC
            LIMIT $1
            """,
            bounded_limit,
            _vector_literal(embedding),
            normalized,
            MIN_VECTOR_SCORE,
            patterns,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT
                vd.id AS document_id,
                vd.filename,
                vd.classification,
                vd.content_type,
                vd.storage_tier,
                vd.status,
                vc.chunk_index,
                vc.content,
                vc.created_at,
                NULL::double precision AS vector_score,
                ts_rank_cd(
                    to_tsvector('simple', vc.content || ' ' || vd.filename),
                    websearch_to_tsquery('simple', $2)
                ) AS text_rank,
                ts_rank_cd(
                    to_tsvector('simple', vc.content || ' ' || vd.filename),
                    websearch_to_tsquery('simple', $2)
                ) AS score
            FROM vault_chunks vc
            JOIN vault_documents vd ON vd.id = vc.document_id
            WHERE to_tsvector('simple', vc.content || ' ' || vd.filename)
                    @@ websearch_to_tsquery('simple', $2)
               OR vc.content ILIKE ANY($3::text[])
               OR vd.filename ILIKE ANY($3::text[])
            ORDER BY score DESC, vc.created_at DESC
            LIMIT $1
            """,
            bounded_limit,
            normalized,
            patterns,
        )

    return [_row_to_match(row, normalized) for row in rows]


def vault_context_block(matches: list[VaultSearchMatch]) -> str:
    if not matches:
        return ""

    lines = [
        "Context from Alpha vault documents:",
        "Use these excerpts only as supporting context; do not invent facts that are not present.",
    ]
    for index, match in enumerate(matches, start=1):
        lines.append(
            f"[{index}] {match.filename} / chunk {match.chunk_index} "
            f"({match.classification}): {match.excerpt}"
        )
    block = "\n".join(lines)
    if len(block) > MAX_CONTEXT_CHARS:
        return block[: MAX_CONTEXT_CHARS - 3].rstrip() + "..."
    return block


def _row_to_match(row: Any, query: str) -> VaultSearchMatch:
    created_at = row["created_at"]
    if isinstance(created_at, datetime):
        created_at_value = created_at.isoformat()
    elif created_at is None:
        created_at_value = None
    else:
        created_at_value = str(created_at)

    vector_score = row["vector_score"]
    text_rank = row["text_rank"] or 0.0
    score = row["score"] or 0.0
    return VaultSearchMatch(
        document_id=str(row["document_id"]),
        filename=str(row["filename"]),
        classification=str(row["classification"]),
        content_type=str(row["content_type"]),
        storage_tier=str(row["storage_tier"]),
        status=str(row["status"]),
        chunk_index=int(row["chunk_index"]),
        excerpt=_excerpt(str(row["content"]), query),
        score=float(score),
        vector_score=None if vector_score is None else float(vector_score),
        text_rank=float(text_rank),
        created_at=created_at_value,
    )


def _excerpt(content: str, query: str) -> str:
    compact = " ".join(content.split())
    if len(compact) <= MAX_EXCERPT_CHARS:
        return compact

    folded = compact.casefold()
    terms = _query_terms(query)
    index = -1
    for term in terms:
        index = folded.find(term)
        if index >= 0:
            break
    if index < 0:
        return compact[: MAX_EXCERPT_CHARS - 3] + "..."

    start = max(0, index - 180)
    end = min(len(compact), start + MAX_EXCERPT_CHARS)
    if end - start < MAX_EXCERPT_CHARS:
        start = max(0, end - MAX_EXCERPT_CHARS)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"
