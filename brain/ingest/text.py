from __future__ import annotations

from typing import Any

import httpx
from fastapi import Request

from brain.core.config import OLLAMA_URL
from brain.db.rls import rls_connection
from jarvis_common.logging_config import get_logger

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

logger = get_logger("alpha_brain")


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


async def _embed_text(text: str) -> list[float] | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": "all-minilm", "prompt": text},
            )
            if response.status_code != 200:
                return None
            data = response.json()
            embedding = data.get("embedding")
            if embedding is None:
                return None
            return [float(x) for x in embedding]
    except Exception:
        return None


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank:
                out.append("")
            previous_blank = True
            continue
        out.append(line)
        previous_blank = False
    return "\n".join(out).strip()


def _chunk_text(text: str) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
    start = 0
    size = len(text)
    while start < size:
        piece = text[start : start + CHUNK_SIZE].strip()
        if len(piece) >= 20:
            chunks.append(piece)
        if start + CHUNK_SIZE >= size:
            break
        start += step
    return chunks


def _decode_text(file_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


async def ingest_extracted_text(
    *,
    text: str,
    doc_id: str,
    request: Request,
    source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_text(text)
    chunks = _chunk_text(normalized)
    embedded_count = 0

    try:
        async with rls_connection(request) as db:
            await db.execute("DELETE FROM vault_chunks WHERE document_id = $1", doc_id)
            for index, chunk in enumerate(chunks):
                embedding = await _embed_text(chunk)
                emb_param: str | None
                if embedding is None:
                    emb_param = None
                else:
                    emb_param = _vector_literal(embedding)
                    embedded_count += 1
                await db.execute(
                    """
                    INSERT INTO vault_chunks
                      (document_id, chunk_index, content, embedding)
                    VALUES ($1, $2, $3, $4::vector)
                    """,
                    doc_id,
                    index,
                    chunk,
                    emb_param,
                )

        result: dict[str, Any] = {
            "doc_id": doc_id,
            "source": source,
            "char_count": len(normalized),
            "chunk_count": len(chunks),
            "embedded_count": embedded_count,
        }
        if extra:
            result.update(extra)
        return result
    except Exception as exc:
        logger.exception("ingest_extracted_text failed: %s", exc)
        return {"doc_id": doc_id, "source": source, "error": str(exc)}


async def ingest_plain_text(
    *,
    file_bytes: bytes,
    filename: str,
    doc_id: str,
    request: Request,
) -> dict[str, Any]:
    try:
        text = _decode_text(file_bytes)
        return await ingest_extracted_text(
            text=text,
            doc_id=doc_id,
            request=request,
            source="text",
            extra={"filename": filename},
        )
    except Exception as exc:
        logger.exception("ingest_plain_text failed: %s", exc)
        return {"doc_id": doc_id, "source": "text", "error": str(exc)}
