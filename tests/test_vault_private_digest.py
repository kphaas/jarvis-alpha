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
async def test_vault_private_digest_invokes_obsidian_skillrunner(monkeypatch) -> None:
    doc_id = uuid4()
    seen = {}

    class FakeConnection:
        async def fetchrow(self, sql, *args):
            seen["lookup"] = (sql, args)
            return {"id": doc_id}

    class FakeSkillConnection:
        pass

    @asynccontextmanager
    async def fake_vault_rls_connection(request):
        yield FakeConnection()

    @asynccontextmanager
    async def fake_platform_admin_connection(**kwargs):
        seen["platform_admin"] = kwargs
        yield FakeSkillConnection()

    class FakeResult:
        requires_approval = False
        denied = False
        output = {
            "status": "created",
            "path": "AT-0/Private Document Digests/resume.md",
        }

    class FakeRunner:
        async def run(self, conn, invocation, *, payload=None):
            seen["conn"] = conn
            seen["invocation"] = invocation
            seen["payload"] = payload
            return FakeResult()

    monkeypatch.setattr(vault_routes, "check_scopes", lambda *args: None)
    monkeypatch.setattr(
        vault_routes,
        "vault_rls_connection",
        fake_vault_rls_connection,
    )
    monkeypatch.setattr(
        vault_routes,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )
    monkeypatch.setattr(vault_routes, "build_skill_runner", lambda: FakeRunner())

    result = await vault_routes.vault_private_digest(
        vault_routes.VaultPrivateDigestRequest(
            title="Resume Digest",
            body="Metadata only.",
            tags=["talent-ops", "resume"],
            document_id=doc_id,
            source_name="resume.docx",
            idempotency_key="talentops-resume-doc-1",
        ),
        SimpleNamespace(state=SimpleNamespace(workspace_id=None)),
    )

    assert result["status"] == "ok"
    assert result["digest"]["status"] == "created"
    assert seen["platform_admin"] == {
        "source": "http",
        "audit_actor": "vault_private_digest",
    }
    assert seen["invocation"].agent_id == "dream_mode"
    assert seen["invocation"].skill_name == "notes.write_private_digest"
    assert seen["invocation"].idempotency_key == "talentops-resume-doc-1"
    assert seen["payload"]["document_id"] == str(doc_id)
    assert seen["payload"]["source_name"] == "resume.docx"


@pytest.mark.asyncio
async def test_vault_private_digest_requires_existing_document(monkeypatch) -> None:
    doc_id = uuid4()

    class FakeConnection:
        async def fetchrow(self, sql, *args):
            return None

    @asynccontextmanager
    async def fake_vault_rls_connection(request):
        yield FakeConnection()

    monkeypatch.setattr(vault_routes, "check_scopes", lambda *args: None)
    monkeypatch.setattr(
        vault_routes,
        "vault_rls_connection",
        fake_vault_rls_connection,
    )

    with pytest.raises(vault_routes.HTTPException) as exc:
        await vault_routes.vault_private_digest(
            vault_routes.VaultPrivateDigestRequest(
                title="Resume Digest",
                body="Metadata only.",
                document_id=doc_id,
                idempotency_key="talentops-resume-doc-1",
            ),
            SimpleNamespace(state=SimpleNamespace(workspace_id=None)),
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_vault_private_digest_surfaces_approval_required(monkeypatch) -> None:
    doc_id = uuid4()

    class FakeConnection:
        async def fetchrow(self, sql, *args):
            return {"id": doc_id}

    @asynccontextmanager
    async def fake_vault_rls_connection(request):
        yield FakeConnection()

    @asynccontextmanager
    async def fake_platform_admin_connection(**kwargs):
        yield object()

    class FakeResult:
        requires_approval = True
        denied = False
        approval_queue_id = "queue-1"
        approval_status = "pending"

    class FakeRunner:
        async def run(self, conn, invocation, *, payload=None):
            return FakeResult()

    monkeypatch.setattr(vault_routes, "check_scopes", lambda *args: None)
    monkeypatch.setattr(
        vault_routes,
        "vault_rls_connection",
        fake_vault_rls_connection,
    )
    monkeypatch.setattr(
        vault_routes,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )
    monkeypatch.setattr(vault_routes, "build_skill_runner", lambda: FakeRunner())

    with pytest.raises(vault_routes.HTTPException) as exc:
        await vault_routes.vault_private_digest(
            vault_routes.VaultPrivateDigestRequest(
                title="Resume Digest",
                body="Metadata only.",
                document_id=doc_id,
                idempotency_key="talentops-resume-doc-1",
            ),
            SimpleNamespace(state=SimpleNamespace(workspace_id=None)),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "status": "approval_required",
        "approval_queue_id": "queue-1",
        "approval_status": "pending",
    }
