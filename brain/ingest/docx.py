from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Any

from fastapi import Request

from brain.ingest.text import ingest_extracted_text
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx_text(file_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        try:
            document_xml = archive.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("DOCX missing word/document.xml") from exc

    root = ET.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{WORD_NS}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{WORD_NS}tab":
                parts.append("\t")
            elif node.tag == f"{WORD_NS}br":
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


async def ingest_docx(
    *,
    file_bytes: bytes,
    doc_id: str,
    request: Request,
) -> dict[str, Any]:
    try:
        text = extract_docx_text(file_bytes)
        return await ingest_extracted_text(
            text=text,
            doc_id=doc_id,
            request=request,
            source="docx",
        )
    except Exception as exc:
        logger.exception("ingest_docx failed: %s", exc)
        return {"doc_id": doc_id, "source": "docx", "error": str(exc)}
