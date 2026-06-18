from __future__ import annotations

import io
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
import zipfile

import openpyxl
import pytest

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://localhost:8080")
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")

from brain.ingest.docx import extract_docx_text
from brain.ingest.excel import ingest_excel
from brain.ingest import text as text_ingest
from brain.ingest.text import _chunk_text, _decode_text
from brain.routes.vault import _vault_workspace_id
from brain.services import vault_security


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


def _xlsx_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Role", "Evidence"])
    sheet.append(["Staff Engineer", "Built private document ingestion"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
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


@pytest.mark.asyncio
async def test_vault_rls_connection_maps_scoped_service_to_platform_admin(
    monkeypatch,
) -> None:
    seen = {}

    @asynccontextmanager
    async def fake_rls_context_connection(ctx, *, set_app_role=False):
        seen["ctx"] = ctx
        seen["set_app_role"] = set_app_role
        yield "vault-conn"

    monkeypatch.setattr(
        vault_security,
        "rls_context_connection",
        fake_rls_context_connection,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(
            actor_type="service",
            role=None,
            scopes=["vault.write"],
            user_id="endpoint_service",
            user_sub="endpoint_service",
            workspace_id=None,
        )
    )

    async with vault_security.vault_rls_connection(request) as conn:
        assert conn == "vault-conn"

    assert seen["set_app_role"] is True
    assert seen["ctx"].role == "platform_admin"
    assert seen["ctx"].user_id == "endpoint_service"
    assert seen["ctx"].workspace_id == "personal"
    assert request.state.workspace_id == "personal"


@pytest.mark.asyncio
async def test_text_ingestion_uses_vault_rls_connection(monkeypatch) -> None:
    calls = []

    class FakeConnection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    @asynccontextmanager
    async def fake_vault_rls_connection(request):
        calls.append(("vault_rls_connection", request))
        yield FakeConnection()

    async def fake_embed_text(text: str):
        return None

    request = SimpleNamespace(state=SimpleNamespace(scopes=["vault.write"]))
    monkeypatch.setattr(
        vault_security,
        "vault_rls_connection",
        fake_vault_rls_connection,
    )
    monkeypatch.setattr(text_ingest, "_embed_text", fake_embed_text)

    result = await text_ingest.ingest_extracted_text(
        text="Supported career fact from a private resume document.",
        doc_id="doc-123",
        request=request,
        source="text",
    )

    assert result["chunk_count"] == 1
    assert calls[0] == ("vault_rls_connection", request)
    assert any("INSERT INTO vault_chunks" in sql for sql, _ in calls[1:])


@pytest.mark.asyncio
async def test_excel_ingestion_uses_vault_rls_connection(monkeypatch) -> None:
    calls = []

    class FakeConnection:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    @asynccontextmanager
    async def fake_vault_rls_connection(request):
        calls.append(("vault_rls_connection", request))
        yield FakeConnection()

    request = SimpleNamespace(state=SimpleNamespace(scopes=["vault.write"]))
    monkeypatch.setattr(
        vault_security,
        "vault_rls_connection",
        fake_vault_rls_connection,
    )

    result = await ingest_excel(
        file_bytes=_xlsx_bytes(),
        filename="career-facts.xlsx",
        doc_id="doc-123",
        request=request,
    )

    assert result["row_count"] == 1
    assert calls[0] == ("vault_rls_connection", request)
    assert any("CREATE TABLE IF NOT EXISTS" in sql for sql, _ in calls[1:])
