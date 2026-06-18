import io

import pdfplumber
from fastapi import Request

from brain.ingest.text import ingest_extracted_text
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")


async def ingest_pdf(
    file_bytes: bytes,
    doc_id: str,
    request: Request,
    workspace_id: str | None = None,
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

        return await ingest_extracted_text(
            text="\n".join(page_texts),
            doc_id=doc_id,
            request=request,
            source="pdf",
            extra={"page_count": page_count, "error_pages": error_pages},
        )
    except Exception as e:
        logger.exception("ingest_pdf failed: %s", e)
        return {"doc_id": doc_id, "error": str(e)}
