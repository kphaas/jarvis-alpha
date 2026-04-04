import io
from typing import Optional

import httpx
import pdfplumber

from brain.config.logging_config import get_logger
from brain.core.config import OLLAMA_URL
from brain.db.session import get_db

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

logger = get_logger("alpha_brain")


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


async def _embed_text(text: str) -> Optional[list[float]]:
    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": "all-minilm", "prompt": text},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            emb = data.get("embedding")
            if emb is None:
                return None
            return [float(x) for x in emb]
    except Exception:
        return None


def _chunk_text(text: str) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
    start = 0
    n = len(text)
    while start < n:
        piece = text[start : start + CHUNK_SIZE]
        if len(piece) >= 20:
            chunks.append(piece)
        if start + CHUNK_SIZE >= n:
            break
        start += step
    return chunks


async def ingest_pdf(
    file_bytes: bytes,
    doc_id: str,
    workspace_id: Optional[str] = None,
) -> dict:
    """
    Extract text from PDF, chunk, embed, store in vault_chunks.
    Returns: {doc_id, page_count, chunk_count, error_pages}
    """
    _ = workspace_id
    try:
        error_pages = 0
        page_texts: list[str] = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = pdf.pages
            for page in pages:
                raw = page.extract_text()
                if raw is None:
                    error_pages += 1
                    page_texts.append("")
                else:
                    page_texts.append(raw)
            page_count = len(pages)

        full_text = "\n".join(page_texts)
        chunks = _chunk_text(full_text)
        embedded_count = 0

        for idx, chunk in enumerate(chunks):
            embedding = await _embed_text(chunk)
            emb_param: Optional[str]
            if embedding is None:
                emb_param = None
            else:
                emb_param = _vector_literal(embedding)
                embedded_count += 1
            async with get_db("anon") as db:
                await db.execute(
                    """
                    INSERT INTO vault_chunks
                      (document_id, chunk_index, content, embedding)
                    VALUES ($1, $2, $3, $4::vector)
                    """,
                    doc_id,
                    idx,
                    chunk,
                    emb_param,
                )

        return {
            "doc_id": doc_id,
            "page_count": page_count,
            "chunk_count": len(chunks),
            "embedded_count": embedded_count,
            "error_pages": error_pages,
        }
    except Exception as e:
        logger.exception("ingest_pdf failed: %s", e)
        return {"doc_id": doc_id, "error": str(e)}
