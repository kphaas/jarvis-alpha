from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://localhost:8080")
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")

from brain.middleware.approval_classes import classify_route
from brain.routes.ask import _can_read_vault, _ensure_vault_workspace
from brain.services.vault_recall import (
    MAX_LIMIT,
    VaultSearchMatch,
    search_vault_chunks,
    vault_context_block,
)


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.args = ()
        self.called = False

    async def fetch(self, sql, *args):
        self.called = True
        self.sql = sql
        self.args = args
        return self.rows


def _row(content: str = "Ken has Staff Platform evidence with Python and FastAPI."):
    return {
        "document_id": "5f8f8f8f-0000-4000-8000-000000000001",
        "filename": "Ken Resume.pdf",
        "classification": "40_PRIVATE",
        "content_type": "application/pdf",
        "storage_tier": "unraid",
        "status": "archived",
        "chunk_index": 2,
        "content": content,
        "created_at": datetime(2026, 6, 18, tzinfo=timezone.utc),
        "vector_score": 0.82,
        "text_rank": 0.12,
        "score": 0.645,
    }


@pytest.mark.asyncio
async def test_search_vault_chunks_uses_vector_recall_when_embedding_available():
    conn = FakeConn([_row()])

    matches = await search_vault_chunks(
        conn,
        query="Staff Platform Python",
        embedding=[0.1, 0.2, 0.3],
        limit=999,
    )

    assert conn.called is True
    assert "<=>" in conn.sql
    assert conn.args[0] == MAX_LIMIT
    assert conn.args[1] == "[0.1,0.2,0.3]"
    assert matches[0].filename == "Ken Resume.pdf"
    assert matches[0].classification == "40_PRIVATE"
    assert "Staff Platform" in matches[0].excerpt
    assert matches[0].to_public_dict()["score"] == 0.645


@pytest.mark.asyncio
async def test_search_vault_chunks_falls_back_to_lexical_search_without_embedding():
    row = _row()
    row["vector_score"] = None
    conn = FakeConn([row])

    matches = await search_vault_chunks(
        conn,
        query="FastAPI",
        embedding=None,
        limit=3,
    )

    assert conn.called is True
    assert "<=>" not in conn.sql
    assert conn.args[0] == 3
    assert conn.args[1] == "FastAPI"
    assert matches[0].vector_score is None


@pytest.mark.asyncio
async def test_search_vault_chunks_skips_empty_queries():
    conn = FakeConn([])

    matches = await search_vault_chunks(conn, query="   ", embedding=None)

    assert matches == []
    assert conn.called is False


def test_vault_context_block_includes_sources_and_grounding_instruction():
    match = VaultSearchMatch(
        document_id="5f8f8f8f-0000-4000-8000-000000000001",
        filename="Ken Resume.pdf",
        classification="40_PRIVATE",
        content_type="application/pdf",
        storage_tier="unraid",
        status="archived",
        chunk_index=2,
        excerpt="Staff Platform leadership evidence.",
        score=0.5,
        vector_score=0.6,
        text_rank=0.1,
        created_at="2026-06-18T00:00:00+00:00",
    )
    block = vault_context_block([match])

    assert "Context from Alpha vault documents" in block
    assert "do not invent facts" in block
    assert "Ken Resume.pdf / chunk 2 (40_PRIVATE)" in block
    assert "Staff Platform leadership evidence." in block


def test_vault_recall_routes_are_classified_as_reads():
    assert classify_route("POST", "/v1/vault/search") == ["read"]
    assert classify_route("POST", "/v1/vault/ask") == [
        "read",
        "external_call",
        "cost_incurring",
    ]
    assert classify_route("POST", "/v1/vault/digests/private") == ["write"]


def test_ask_vault_recall_requires_admin_or_vault_read_scope():
    admin_request = SimpleNamespace(
        state=SimpleNamespace(actor_type="user", role="admin", scopes=[])
    )
    reader_request = SimpleNamespace(
        state=SimpleNamespace(actor_type="service", role=None, scopes=["vault.read"])
    )
    writer_request = SimpleNamespace(
        state=SimpleNamespace(actor_type="service", role=None, scopes=["vault.write"])
    )

    assert _can_read_vault(admin_request) is True
    assert _can_read_vault(reader_request) is True
    assert _can_read_vault(writer_request) is False


def test_ask_vault_recall_defaults_missing_workspace_to_personal():
    request = SimpleNamespace(state=SimpleNamespace(workspace_id=None))

    _ensure_vault_workspace(request)

    assert request.state.workspace_id == "personal"
