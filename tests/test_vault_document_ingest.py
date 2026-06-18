from __future__ import annotations

import io
import os
from types import SimpleNamespace
import zipfile

import pytest

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://localhost:8080")
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")

from brain.ingest.docx import extract_docx_text
from brain.ingest.text import _chunk_text, _decode_text
from brain.routes.vault import _vault_workspace_id


def _docx_bytes(document_xml: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _zip_bytes(path: str, content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(path, content)
    return buffer.getvalue()


def test_extract_docx_text_reads_paragraphs_tabs_and_breaks() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Senior engineer</w:t></w:r></w:p>
        <w:p>
          <w:r><w:t>Python</w:t></w:r>
          <w:r><w:tab /></w:r>
          <w:r><w:t>FastAPI</w:t></w:r>
          <w:r><w:br /></w:r>
          <w:r><w:t>Postgres</w:t></w:r>
        </w:p>
      </w:body>
    </w:document>
    """

    text = extract_docx_text(_docx_bytes(xml))

    assert text == "Senior engineer\nPython\tFastAPI\nPostgres"


def test_extract_docx_text_rejects_invalid_docx() -> None:
    with pytest.raises(ValueError, match="DOCX missing word/document.xml"):
        extract_docx_text(_zip_bytes("docProps/core.xml", "<root />"))


def test_decode_text_handles_utf8_bom() -> None:
    assert _decode_text("hello".encode("utf-8-sig")) == "hello"


def test_chunk_text_uses_overlap_for_long_text() -> None:
    chunks = _chunk_text("x" * 700)

    assert len(chunks) == 2
    assert chunks[0] == "x" * 512
    assert chunks[1] == "x" * 238


def test_vault_workspace_id_defaults_service_tokens_to_personal() -> None:
    request = SimpleNamespace(state=SimpleNamespace(workspace_id=None))

    assert _vault_workspace_id(request) == "personal"
    assert request.state.workspace_id == "personal"


def test_vault_workspace_id_preserves_explicit_workspace() -> None:
    request = SimpleNamespace(state=SimpleNamespace(workspace_id="  tax-workspace  "))

    assert _vault_workspace_id(request) == "tax-workspace"
    assert request.state.workspace_id == "tax-workspace"
