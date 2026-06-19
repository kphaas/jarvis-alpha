from __future__ import annotations

import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://localhost:8080")
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")

from brain.routes import vault as vault_routes


@pytest.mark.asyncio
async def test_vault_pipeline_confirm_persists_archive_storage_tier(
    monkeypatch,
) -> None:
    doc_id = uuid4()
    calls = []

    class FakeConnection:
        async def fetchrow(self, sql, *args):
            assert args == ("pipeline-123",)
            return {
                "id": "pipeline-123",
                "filename": "resume.txt",
                "local_path": "/tmp/resume.txt",
                "content_type": "text/plain",
                "doc_id": doc_id,
                "classification": "40_PRIVATE",
            }

        async def execute(self, sql, *args):
            calls.append((sql, args))

    @asynccontextmanager
    async def fake_vault_rls_connection(request):
        yield FakeConnection()

    async def fake_archive_document(**kwargs):
        assert kwargs["classification"] == "40_PRIVATE"
        return {
            "archive_path": "unraid:/mnt/user/Documents/40_LEGAL/resume.txt",
            "tier": "unraid",
        }

    monkeypatch.setattr(vault_routes, "check_scopes", lambda *args: None)
    monkeypatch.setattr(
        vault_routes,
        "vault_rls_connection",
        fake_vault_rls_connection,
    )
    monkeypatch.setattr(vault_routes, "archive_document", fake_archive_document)

    result = await vault_routes.vault_pipeline_confirm(
        "pipeline-123",
        SimpleNamespace(state=SimpleNamespace(workspace_id=None)),
    )

    assert result["tier"] == "unraid"
    document_updates = [
        args for sql, args in calls if "UPDATE vault_documents" in " ".join(sql.split())
    ]
    assert document_updates == [
        (
            "unraid:/mnt/user/Documents/40_LEGAL/resume.txt",
            "archived",
            "unraid",
            str(doc_id),
        )
    ]
