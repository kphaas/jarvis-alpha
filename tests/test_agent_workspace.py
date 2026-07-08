from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8283")
os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:11434")

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import registry
from brain.services import agent_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fresh_created_at() -> datetime:
    return datetime.now(tz=UTC)


def test_local_workspace_init_writes_manifest_and_layout(tmp_path: Path) -> None:
    backend = agent_workspace.LocalWorkspaceBackend(tmp_path)
    run_id = UUID("11111111-1111-1111-1111-111111111111")

    manifest = backend.init_workspace(
        run_id,
        "internet_scout",
        ["memory.proposal_required"],
        "memory.review",
        "standard",
        created_at=_fresh_created_at(),
    )

    workspace_root = tmp_path / str(run_id)
    assert manifest.workspace_root == str(workspace_root)
    assert (workspace_root / "manifest.json").exists()
    assert (workspace_root / "artifacts.jsonl").exists()
    assert (workspace_root / "input").is_dir()
    assert (workspace_root / "working").is_dir()
    assert (workspace_root / "outputs").is_dir()
    assert (workspace_root / "logs").is_dir()

    payload = json.loads((workspace_root / "manifest.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == str(run_id)
    assert payload["agent_id"] == "internet_scout"
    assert payload["policy_labels"] == ["memory.proposal_required"]


def test_stage_text_rejects_path_traversal(tmp_path: Path) -> None:
    backend = agent_workspace.LocalWorkspaceBackend(tmp_path)
    run_id = UUID("22222222-2222-2222-2222-222222222222")
    backend.init_workspace(run_id, "buddy", [], None, "standard")

    with pytest.raises(agent_workspace.WorkspacePathError, match="workspace_root"):
        backend.stage_text(run_id, "../escape.txt", "nope", "note")


def test_workspace_writes_append_to_artifact_ledger(tmp_path: Path) -> None:
    backend = agent_workspace.LocalWorkspaceBackend(tmp_path)
    run_id = UUID("33333333-3333-3333-3333-333333333333")
    backend.init_workspace(run_id, "buddy", ["paper_only"], None, "standard")

    first = backend.write_text(
        run_id,
        "working/notes.txt",
        "hello",
        "working_note",
        policy_labels=["paper_only"],
    )
    second = backend.write_bytes(
        run_id,
        "outputs/report.bin",
        b"abc",
        "output_blob",
        content_type="application/octet-stream",
        policy_labels=["paper_only"],
    )

    lines = (
        (tmp_path / str(run_id) / "artifacts.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["artifact_id"] == first.artifact_id
    assert payloads[1]["artifact_id"] == second.artifact_id
    assert payloads[0]["relative_path"] == "working/notes.txt"
    assert payloads[1]["relative_path"] == "outputs/report.bin"


def test_stage_upload_stream_rejects_oversized_payload(tmp_path: Path) -> None:
    backend = agent_workspace.LocalWorkspaceBackend(
        tmp_path,
        max_artifact_bytes=8,
        max_workspace_bytes=128,
    )
    run_id = UUID("33333333-3333-3333-3333-333333333334")
    backend.init_workspace(run_id, "buddy", [], None, "standard")

    with pytest.raises(ValueError, match="artifact exceeds max size"):
        backend.stage_upload_stream(
            run_id,
            "outputs/large.bin",
            BytesIO(b"123456789"),
            "output_blob",
            content_type="application/octet-stream",
        )


def test_preview_text_is_bounded_and_sanitized(tmp_path: Path) -> None:
    backend = agent_workspace.LocalWorkspaceBackend(tmp_path, preview_bytes=6)
    run_id = UUID("33333333-3333-3333-3333-333333333335")
    backend.init_workspace(run_id, "buddy", [], None, "standard")
    backend.write_bytes(
        run_id,
        "outputs/report.txt",
        b"abc\x00defghi",
        "report",
        content_type="text/plain",
    )

    preview = backend.preview_text(run_id, "outputs/report.txt")

    assert preview.preview_available is True
    assert preview.preview_bytes == 6
    assert preview.truncated is True
    assert preview.text == "abc\ufffdde"


@pytest.mark.asyncio
async def test_workspace_init_route_is_idempotent_and_persists_policy_labels(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = agent_workspace.LocalWorkspaceBackend(tmp_path)
    conn = _FakeWorkspaceConn()

    monkeypatch.setattr(registry, "check_scopes", lambda *args: None)
    monkeypatch.setattr(registry, "get_workspace_backend", lambda: backend)
    monkeypatch.setattr(registry, "rls_connection", lambda request: _FakeRls(conn))

    request = _request()
    run_id = UUID("44444444-4444-4444-4444-444444444444")

    first = await registry.init_agent_run_workspace(run_id, request)
    second = await registry.init_agent_run_workspace(run_id, request)

    assert first.workspace_uri == f"agentfs://runs/{run_id}"
    assert second.workspace_uri == first.workspace_uri
    assert first.workspace_state == "ready"
    assert first.raw_access_mode == "download_only"
    assert first.usage_bytes == 0
    assert "workspace_root" not in first.model_dump()
    assert first.policy_labels == [
        "finance.paper_only",
        "memory.proposal_required",
    ]
    manifest_payload = json.loads(
        (tmp_path / str(run_id) / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest_payload["policy_labels"] == first.policy_labels
    assert conn.workspace_update_count == 1


@pytest.mark.asyncio
async def test_create_agent_run_artifact_stores_metadata_without_body_in_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = agent_workspace.LocalWorkspaceBackend(tmp_path)
    conn = _FakeWorkspaceConn()

    monkeypatch.setattr(registry, "check_scopes", lambda *args: None)
    monkeypatch.setattr(registry, "get_workspace_backend", lambda: backend)
    monkeypatch.setattr(registry, "rls_connection", lambda request: _FakeRls(conn))

    request = _request()
    run_id = UUID("55555555-5555-5555-5555-555555555555")
    large_text = "artifact-body-" * 2048

    out = await registry.create_agent_run_artifact(
        run_id,
        request,
        kind="working_note",
        relative_path="working/plan.txt",
        text=large_text,
        content_type="text/plain",
        file=None,
    )

    assert out.relative_path == "working/plan.txt"
    assert out.size_bytes == len(large_text.encode("utf-8"))
    assert conn.artifact_insert_args is not None
    assert not any(
        isinstance(arg, str) and large_text in arg for arg in conn.artifact_insert_args
    )
    stored_path = tmp_path / str(run_id) / "working" / "plan.txt"
    assert stored_path.read_text(encoding="utf-8") == large_text


@pytest.mark.asyncio
async def test_list_agent_run_artifacts_reads_db_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeWorkspaceConn()
    conn.artifact_rows = [
        {
            "id": UUID("66666666-6666-6666-6666-666666666666"),
            "run_id": UUID("44444444-4444-4444-4444-444444444444"),
            "relative_path": "outputs/report.txt",
            "kind": "report",
            "content_type": "text/plain",
            "size_bytes": 120,
            "sha256": "a" * 64,
            "policy_labels": '["memory.proposal_required"]',
            "created_at": datetime(2026, 6, 30, 18, 30, tzinfo=UTC),
        }
    ]

    monkeypatch.setattr(registry, "check_scopes", lambda *args: None)
    monkeypatch.setattr(
        registry,
        "get_workspace_backend",
        lambda: (_ for _ in ()).throw(AssertionError("workspace backend not needed")),
    )
    monkeypatch.setattr(registry, "rls_connection", lambda request: _FakeRls(conn))

    out = await registry.list_agent_run_artifacts(
        UUID("44444444-4444-4444-4444-444444444444"),
        _request(),
    )

    assert out.count == 1
    assert out.artifacts[0].relative_path == "outputs/report.txt"
    assert out.artifacts[0].policy_labels == ["memory.proposal_required"]


@pytest.mark.asyncio
async def test_get_agent_run_artifact_content_reads_workspace_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = agent_workspace.LocalWorkspaceBackend(tmp_path)
    conn = _FakeWorkspaceConn()
    run_id = UUID("77777777-7777-7777-7777-777777777777")

    manifest = backend.init_workspace(
        run_id,
        "internet_scout",
        ["memory.proposal_required"],
        "memory.review",
        "standard",
        created_at=_fresh_created_at(),
    )
    conn.workspace_root = manifest.workspace_root
    record = backend.write_text(
        run_id,
        "outputs/report.json",
        '{"ok":true}\n',
        "report",
        content_type="application/json",
        policy_labels=["memory.proposal_required"],
        workspace_root=manifest.workspace_root,
    )
    conn.artifact_row = {
        "id": UUID(record.artifact_id),
        "run_id": run_id,
        "relative_path": record.relative_path,
        "kind": record.kind,
        "content_type": record.content_type,
    }

    monkeypatch.setattr(registry, "check_scopes", lambda *args: None)
    monkeypatch.setattr(registry, "get_workspace_backend", lambda: backend)
    monkeypatch.setattr(registry, "rls_connection", lambda request: _FakeRls(conn))

    response = await registry.get_agent_run_artifact_content(
        run_id,
        UUID(record.artifact_id),
        _request(),
    )

    assert response.media_type == "application/json"
    assert response.body == b'{"ok":true}\n'
    assert (
        response.headers["content-disposition"] == 'attachment; filename="report.json"'
    )


@pytest.mark.asyncio
async def test_preview_agent_run_artifact_returns_bounded_safe_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = agent_workspace.LocalWorkspaceBackend(tmp_path, preview_bytes=5)
    conn = _FakeWorkspaceConn()
    run_id = UUID("78777777-7777-7777-7777-777777777777")

    manifest = backend.init_workspace(
        run_id,
        "internet_scout",
        ["memory.proposal_required"],
        "memory.review",
        "standard",
        created_at=_fresh_created_at(),
    )
    conn.workspace_root = manifest.workspace_root
    record = backend.write_text(
        run_id,
        "outputs/report.txt",
        "hello world",
        "report",
        content_type="text/plain",
        policy_labels=["memory.proposal_required"],
        workspace_root=manifest.workspace_root,
    )
    conn.artifact_row = {
        "id": UUID(record.artifact_id),
        "run_id": run_id,
        "relative_path": record.relative_path,
        "kind": record.kind,
        "content_type": record.content_type,
    }

    monkeypatch.setattr(registry, "check_scopes", lambda *args: None)
    monkeypatch.setattr(registry, "get_workspace_backend", lambda: backend)
    monkeypatch.setattr(registry, "rls_connection", lambda request: _FakeRls(conn))

    out = await registry.preview_agent_run_artifact(
        run_id,
        UUID(record.artifact_id),
        _request(),
    )

    assert out.preview_available is True
    assert out.preview_truncated is True
    assert out.preview_text == "hello"
    assert out.raw_access_mode == "download_only"


def test_agent_workspace_routes_are_governed_t2() -> None:
    cases = [
        ("POST", "/v1/agent-runs/11111111-1111-1111-1111-111111111111/workspace/init"),
        ("GET", "/v1/agent-runs/11111111-1111-1111-1111-111111111111/workspace"),
        ("GET", "/v1/agent-runs/11111111-1111-1111-1111-111111111111/artifacts"),
        (
            "GET",
            "/v1/agent-runs/11111111-1111-1111-1111-111111111111/artifacts/"
            "22222222-2222-2222-2222-222222222222/preview",
        ),
        (
            "GET",
            "/v1/agent-runs/11111111-1111-1111-1111-111111111111/artifacts/"
            "22222222-2222-2222-2222-222222222222/download",
        ),
        (
            "GET",
            "/v1/agent-runs/11111111-1111-1111-1111-111111111111/artifacts/"
            "22222222-2222-2222-2222-222222222222/content",
        ),
        ("POST", "/v1/agent-runs/11111111-1111-1111-1111-111111111111/artifacts"),
    ]

    for method, path in cases:
        classes = classify_route(method, path)
        assert determine_risk_tier(classes) == "T2"


def test_agent_workspace_migration_is_reversible_and_rls_guarded() -> None:
    migration = (
        REPO_ROOT / "brain/db/migrations/20260630_190000_alpha_agentfs_workspace.sql"
    )
    rollback = (
        REPO_ROOT
        / "brain/db/rollbacks/20260630_190000_alpha_agentfs_workspace_rollback.sql"
    )

    migration_text = migration.read_text(encoding="utf-8")
    rollback_text = rollback.read_text(encoding="utf-8")

    assert (
        "ADD COLUMN IF NOT EXISTS workspace_root TEXT NOT NULL DEFAULT ''"
        in migration_text
    )
    assert (
        "CREATE TABLE IF NOT EXISTS public.alpha_agent_run_artifacts" in migration_text
    )
    assert "FORCE ROW LEVEL SECURITY" in migration_text
    assert "DROP TABLE IF EXISTS public.alpha_agent_run_artifacts" in rollback_text
    assert "DROP COLUMN IF EXISTS workspace_root" in rollback_text


class _FakeWorkspaceConn:
    def __init__(self) -> None:
        self.workspace_root = ""
        self.workspace_update_count = 0
        self.artifact_insert_args: tuple[object, ...] | None = None
        self.artifact_rows: list[dict[str, object]] = []
        self.artifact_row: dict[str, object] | None = None

    async def fetchrow(self, query: str, *args: object):
        if "FROM public.alpha_agent_runs" in query:
            run_id = args[0]
            return {
                "id": run_id,
                "agent_id": "internet_scout",
                "created_at": _fresh_created_at(),
                "workspace_backend": "local",
                "workspace_root": self.workspace_root,
                "policy_labels": '["finance.paper_only", "memory.proposal_required"]',
                "approval_scope": "memory.review",
                "retention_class": "standard",
            }
        if "FROM public.alpha_agent_run_artifacts" in query:
            return self.artifact_row
        raise AssertionError(query)

    async def fetch(self, query: str, *args: object):
        if "FROM public.alpha_agent_run_artifacts" in query:
            return list(self.artifact_rows)
        raise AssertionError(query)

    async def execute(self, query: str, *args: object):
        if "UPDATE public.alpha_agent_runs" in query:
            self.workspace_update_count += 1
            self.workspace_root = str(args[2])
            return "UPDATE 1"
        if "INSERT INTO public.alpha_agent_run_artifacts" in query:
            self.artifact_insert_args = args
            return "INSERT 0 1"
        if "DELETE FROM public.alpha_agent_run_artifacts" in query:
            return "DELETE 0"
        raise AssertionError(query)


class _FakeRls:
    def __init__(self, conn: _FakeWorkspaceConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _FakeWorkspaceConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _request():
    return SimpleNamespace(
        state=SimpleNamespace(user_id="ken", workspace_id="helm", role="admin")
    )
