"""Skill and agent registry API."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID
from typing import Literal

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field

from brain.agents.manual_run import (
    canonical_agent_id,
    manual_run_eligibility,
    run_agent_now,
)
from brain.db.pool import get_pool
from brain.db.rls import rls_connection
from brain.middleware.scopes import check_scopes
from brain.registry.models import SkillManifestV1
from brain.services.agent_workspace import (
    WorkspaceArtifactRecord,
    WorkspaceArtifactPreview,
    WorkspaceManifest,
    WorkspacePathError,
    WorkspaceRetentionExpiredError,
    get_workspace_backend,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1", tags=["registry"])


class SkillOut(BaseModel):
    name: str
    domain: str
    action: str
    description: str
    approval_tier: str
    scope: str
    status: str
    mutates_state: bool
    body_access: bool
    idempotency_required: bool
    owner: str
    manifest: SkillManifestV1 | None = None
    metadata: dict = Field(default_factory=dict)


class SkillListOut(BaseModel):
    count: int
    skills: list[SkillOut]


class AgentOut(BaseModel):
    agent_id: str
    display_name: str
    purpose: str
    risk_tier: str
    status: str
    enabled: bool
    owner: str
    cadence: str | None = None
    launch_label: str | None = None
    allowed_skills: list[str] = Field(default_factory=list)
    allowed_scopes: list[str] = Field(default_factory=list)
    cost_daily_cap_usd: float | None = None
    model_policy: dict = Field(default_factory=dict)
    approval_policy: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class AgentListOut(BaseModel):
    count: int
    agents: list[AgentOut]


class AgentEventOut(BaseModel):
    id: str
    agent_id: str
    run_id: str | None = None
    event_type: str
    severity: str
    title: str
    message: str
    correlation_id: str | None = None
    channel_key: str
    notification_status: str
    notification_error: str | None = None
    payload: dict = Field(default_factory=dict)
    notification_result: dict = Field(default_factory=dict)
    created_at: str
    notified_at: str | None = None


class AgentEventListOut(BaseModel):
    count: int
    events: list[AgentEventOut]


class AgentRunOut(BaseModel):
    id: str
    agent_id: str
    status: str
    trigger_type: str
    trace_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    cost_usd: float
    error_text: str | None = None
    workspace_backend: str
    workspace_uri: str | None = None
    workspace_state: str = "not_initialized"
    policy_labels: list[str] = Field(default_factory=list)
    approval_scope: str | None = None
    retention_class: str
    retention_expires_at: str | None = None
    raw_access_mode: Literal["inline_ok", "download_only"] = "inline_ok"
    artifact_count: int = 0
    metadata: dict = Field(default_factory=dict)
    created_at: str


class AgentRunListOut(BaseModel):
    count: int
    runs: list[AgentRunOut]


class AgentRunWorkspaceOut(BaseModel):
    run_id: str
    agent_id: str
    created_at: str
    workspace_backend: str
    workspace_uri: str
    workspace_state: str
    policy_labels: list[str] = Field(default_factory=list)
    approval_scope: str | None = None
    retention_class: str
    retention_expires_at: str
    usage_bytes: int
    quota_bytes: int
    artifact_max_bytes: int
    preview_max_bytes: int
    raw_access_mode: Literal["inline_ok", "download_only"] = "inline_ok"


class AgentRunArtifactOut(BaseModel):
    artifact_id: str
    run_id: str
    relative_path: str
    kind: str
    content_type: str
    size_bytes: int
    created_at: str
    sha256: str | None = None
    policy_labels: list[str] = Field(default_factory=list)


class AgentRunArtifactListOut(BaseModel):
    count: int
    artifacts: list[AgentRunArtifactOut]


class AgentRunArtifactPreviewOut(BaseModel):
    artifact_id: str
    run_id: str
    relative_path: str
    kind: str
    content_type: str
    preview_text: str | None = None
    preview_truncated: bool = False
    preview_bytes: int = 0
    preview_available: bool = False
    approval_scope: str | None = None
    raw_access_mode: Literal["inline_ok", "download_only"] = "inline_ok"
    retention_expires_at: str | None = None


class AgentStatusOut(BaseModel):
    agent_id: str
    display_name: str
    status: str
    enabled: bool
    risk_tier: str
    cadence: str | None = None
    launch_label: str | None = None
    mattermost_channel_key: str | None = None
    last_run_status: str | None = None
    last_run_at: str | None = None
    last_event_type: str | None = None
    last_event_severity: str | None = None
    last_event_title: str | None = None
    last_event_at: str | None = None


class AgentStatusListOut(BaseModel):
    count: int
    agents: list[AgentStatusOut]


class AgentManualRunOut(BaseModel):
    agent_id: str
    executed: bool
    run_id: str | None = None
    status: str | None = None
    trace_id: str | None = None
    skipped_reason: str | None = None
    error_text: str | None = None


def _jsonb(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _jsonb_list(value) -> list[str]:
    if value is None:
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _skill_from_row(row) -> SkillOut:
    metadata = _jsonb(row["metadata"])
    manifest = metadata.get("manifest")
    return SkillOut(
        name=row["skill_name"],
        domain=row["domain"],
        action=row["action"],
        description=row["description"],
        approval_tier=row["approval_tier"],
        scope=row["scope"],
        status=row["status"],
        mutates_state=row["mutates_state"],
        body_access=row["body_access"],
        idempotency_required=row["idempotency_required"],
        owner=row["owner"],
        manifest=SkillManifestV1.model_validate(manifest) if manifest else None,
        metadata=metadata,
    )


def _agent_from_row(row) -> AgentOut:
    cost_cap = row["cost_daily_cap_usd"]
    return AgentOut(
        agent_id=row["agent_id"],
        display_name=row["display_name"],
        purpose=row["purpose"],
        risk_tier=row["risk_tier"],
        status=row["status"],
        enabled=row["enabled"],
        owner=row["owner"],
        cadence=row["cadence"],
        launch_label=row["launch_label"],
        allowed_skills=list(row["allowed_skills"] or []),
        allowed_scopes=list(row["allowed_scopes"] or []),
        cost_daily_cap_usd=float(cost_cap) if cost_cap is not None else None,
        model_policy=_jsonb(row["model_policy"]),
        approval_policy=_jsonb(row["approval_policy"]),
        metadata=_jsonb(row["metadata"]),
    )


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _agent_event_from_row(row) -> AgentEventOut:
    return AgentEventOut(
        id=str(row["id"]),
        agent_id=row["agent_id"],
        run_id=str(row["run_id"]) if row["run_id"] else None,
        event_type=row["event_type"],
        severity=row["severity"],
        title=row["title"],
        message=row["message"],
        correlation_id=row["correlation_id"],
        channel_key=row["channel_key"],
        notification_status=row["notification_status"],
        notification_error=row["notification_error"],
        payload=_jsonb(row["payload"]),
        notification_result=_jsonb(row["notification_result"]),
        created_at=_iso(row["created_at"]) or "",
        notified_at=_iso(row["notified_at"]),
    )


def _agent_run_from_row(row) -> AgentRunOut:
    backend = get_workspace_backend()
    workspace_initialized = bool(str(row["workspace_root"] or "").strip())
    raw_access_mode = _raw_access_mode(row["approval_scope"])
    return AgentRunOut(
        id=str(row["id"]),
        agent_id=row["agent_id"],
        status=row["status"],
        trigger_type=row["trigger_type"],
        trace_id=row["trace_id"],
        started_at=_iso(row["started_at"]),
        completed_at=_iso(row["completed_at"]),
        cost_usd=float(row["cost_usd"] or 0),
        error_text=row["error_text"],
        workspace_backend=row["workspace_backend"],
        workspace_uri=backend.workspace_uri(row["id"])
        if workspace_initialized
        else None,
        workspace_state=backend.workspace_state(
            created_at=row["created_at"],
            retention_class=row["retention_class"],
            workspace_initialized=workspace_initialized,
        ),
        policy_labels=_jsonb_list(row["policy_labels"]),
        approval_scope=row["approval_scope"],
        retention_class=row["retention_class"],
        retention_expires_at=backend.retention_expires_at(
            row["created_at"],
            row["retention_class"],
        ),
        raw_access_mode=raw_access_mode,
        artifact_count=int(row["artifact_count"] or 0),
        metadata=_jsonb(row["metadata"]),
        created_at=_iso(row["created_at"]) or "",
    )


def _workspace_from_manifest(
    manifest: WorkspaceManifest,
    *,
    usage_bytes: int,
    backend,
) -> AgentRunWorkspaceOut:
    return AgentRunWorkspaceOut(
        run_id=manifest.run_id,
        agent_id=manifest.agent_id,
        created_at=manifest.created_at,
        workspace_backend=manifest.workspace_backend,
        workspace_uri=backend.workspace_uri(manifest.run_id),
        workspace_state=backend.workspace_state(
            created_at=manifest.created_at,
            retention_class=manifest.retention_class,
            workspace_initialized=True,
        ),
        policy_labels=list(manifest.policy_labels),
        approval_scope=manifest.approval_scope,
        retention_class=manifest.retention_class,
        retention_expires_at=backend.retention_expires_at(
            manifest.created_at,
            manifest.retention_class,
        ),
        usage_bytes=usage_bytes,
        quota_bytes=backend.max_workspace_bytes,
        artifact_max_bytes=backend.max_artifact_bytes,
        preview_max_bytes=backend.preview_bytes,
        raw_access_mode=_raw_access_mode(manifest.approval_scope),
    )


def _artifact_from_record(record: WorkspaceArtifactRecord) -> AgentRunArtifactOut:
    return AgentRunArtifactOut(
        artifact_id=record.artifact_id,
        run_id=record.run_id,
        relative_path=record.relative_path,
        kind=record.kind,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        created_at=record.created_at,
        sha256=record.sha256,
        policy_labels=list(record.policy_labels),
    )


def _artifact_preview_from_record(
    row,
    preview: WorkspaceArtifactPreview,
    *,
    approval_scope: str | None,
    retention_expires_at: str,
) -> AgentRunArtifactPreviewOut:
    return AgentRunArtifactPreviewOut(
        artifact_id=str(row["id"]),
        run_id=str(row["run_id"]),
        relative_path=row["relative_path"],
        kind=row["kind"],
        content_type=row["content_type"],
        preview_text=preview.text,
        preview_truncated=preview.truncated,
        preview_bytes=preview.preview_bytes,
        preview_available=preview.preview_available,
        approval_scope=approval_scope,
        raw_access_mode=_raw_access_mode(approval_scope),
        retention_expires_at=retention_expires_at,
    )


def _raw_access_mode(
    approval_scope: str | None,
) -> Literal["inline_ok", "download_only"]:
    return "download_only" if str(approval_scope or "").strip() else "inline_ok"


def _previewable_content_type(content_type: str) -> bool:
    clean = str(content_type or "").strip().lower()
    return (
        clean.startswith("text/")
        or clean == "application/json"
        or clean.endswith("+json")
    )


def _agent_status_from_row(row) -> AgentStatusOut:
    metadata = _jsonb(row["metadata"])
    return AgentStatusOut(
        agent_id=row["agent_id"],
        display_name=row["display_name"],
        status=row["status"],
        enabled=row["enabled"],
        risk_tier=row["risk_tier"],
        cadence=row["cadence"],
        launch_label=row["launch_label"],
        mattermost_channel_key=metadata.get("mattermost_channel_key"),
        last_run_status=row["last_run_status"],
        last_run_at=_iso(row["last_run_at"]),
        last_event_type=row["last_event_type"],
        last_event_severity=row["last_event_severity"],
        last_event_title=row["last_event_title"],
        last_event_at=_iso(row["last_event_at"]),
    )


@router.get("/skills", response_model=SkillListOut)
async def list_skills(
    request: Request,
    domain: str | None = None,
    status: Literal["planned", "active", "disabled", "all"] = Query(default="all"),
) -> SkillListOut:
    check_scopes(request, "skills.read", "agents.read")
    filters: list[str] = []
    params: list[str] = []
    if domain:
        params.append(domain)
        filters.append(f"domain = ${len(params)}")
    if status != "all":
        params.append(status)
        filters.append(f"status = ${len(params)}")
    where = " AND ".join(filters) if filters else "TRUE"

    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            f"""
            SELECT skill_name, domain, action, description, approval_tier, scope,
                   status, mutates_state, body_access, idempotency_required,
                   owner, metadata
            FROM public.alpha_skill_registry
            WHERE {where}
            ORDER BY domain ASC, skill_name ASC
            """,
            *params,
        )
    return SkillListOut(count=len(rows), skills=[_skill_from_row(row) for row in rows])


@router.get("/skills/{skill_name}", response_model=SkillOut)
async def get_skill(skill_name: str, request: Request) -> SkillOut:
    check_scopes(request, "skills.read", "agents.read")
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            SELECT skill_name, domain, action, description, approval_tier, scope,
                   status, mutates_state, body_access, idempotency_required,
                   owner, metadata
            FROM public.alpha_skill_registry
            WHERE skill_name = $1
            """,
            skill_name,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _skill_from_row(row)


@router.get("/agents", response_model=AgentListOut)
async def list_agents(
    request: Request,
    status: Literal["planned", "active", "disabled", "all"] = Query(default="all"),
    enabled: bool | None = None,
) -> AgentListOut:
    check_scopes(request, "agents.read")
    filters: list[str] = []
    params: list = []
    if status != "all":
        params.append(status)
        filters.append(f"status = ${len(params)}")
    if enabled is not None:
        params.append(enabled)
        filters.append(f"enabled = ${len(params)}")
    where = " AND ".join(filters) if filters else "TRUE"

    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            f"""
            SELECT agent_id, display_name, purpose, risk_tier, status, enabled,
                   owner, cadence, launch_label, allowed_skills, allowed_scopes,
                   cost_daily_cap_usd, model_policy, approval_policy, metadata
            FROM public.alpha_agents
            WHERE {where}
            ORDER BY status ASC, agent_id ASC
            """,
            *params,
        )
    return AgentListOut(count=len(rows), agents=[_agent_from_row(row) for row in rows])


@router.get("/agents/status", response_model=AgentStatusListOut)
async def list_agent_statuses(request: Request) -> AgentStatusListOut:
    check_scopes(request, "agents.read")
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT a.agent_id, a.display_name, a.status, a.enabled, a.risk_tier,
                   a.cadence, a.launch_label, a.metadata,
                   lr.status AS last_run_status,
                   lr.last_run_at AS last_run_at,
                   le.event_type AS last_event_type,
                   le.severity AS last_event_severity,
                   le.title AS last_event_title,
                   le.created_at AS last_event_at
            FROM public.alpha_agents a
            LEFT JOIN LATERAL (
                SELECT
                    status,
                    COALESCE(completed_at, started_at, created_at) AS last_run_at
                FROM public.alpha_agent_runs
                WHERE agent_id = a.agent_id
                ORDER BY COALESCE(completed_at, started_at, created_at) DESC,
                         created_at DESC
                LIMIT 1
            ) lr ON TRUE
            LEFT JOIN LATERAL (
                SELECT event_type, severity, title, created_at
                FROM public.alpha_agent_events
                WHERE agent_id = a.agent_id
                ORDER BY created_at DESC
                LIMIT 1
            ) le ON TRUE
            ORDER BY a.status ASC, a.agent_id ASC
            """
        )
    return AgentStatusListOut(
        count=len(rows),
        agents=[_agent_status_from_row(row) for row in rows],
    )


@router.get("/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, request: Request) -> AgentOut:
    check_scopes(request, "agents.read")
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            SELECT agent_id, display_name, purpose, risk_tier, status, enabled,
                   owner, cadence, launch_label, allowed_skills, allowed_scopes,
                   cost_daily_cap_usd, model_policy, approval_policy, metadata
            FROM public.alpha_agents
            WHERE agent_id = $1
            """,
            agent_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_from_row(row)


@router.get("/agents/{agent_id}/events", response_model=AgentEventListOut)
async def list_agent_events(
    agent_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    severity: Literal[
        "debug", "info", "needs_input", "warning", "error", "critical", "all"
    ] = Query(default="all"),
) -> AgentEventListOut:
    check_scopes(request, "agents.read")
    filters = ["agent_id = $1"]
    params: list = [agent_id]
    if severity != "all":
        params.append(severity)
        filters.append(f"severity = ${len(params)}")
    params.append(limit)
    where = " AND ".join(filters)
    async with rls_connection(request) as conn:
        agent_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM public.alpha_agents WHERE agent_id = $1)",
            agent_id,
        )
        if not agent_exists:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = await conn.fetch(
            f"""
            SELECT id, agent_id, run_id, event_type, severity, title, message,
                   correlation_id, channel_key, notification_status,
                   notification_error, payload, notification_result, created_at,
                   notified_at
            FROM public.alpha_agent_events
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return AgentEventListOut(
        count=len(rows),
        events=[_agent_event_from_row(row) for row in rows],
    )


@router.get("/agents/{agent_id}/runs", response_model=AgentRunListOut)
async def list_agent_runs(
    agent_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
) -> AgentRunListOut:
    check_scopes(request, "agents.read")
    async with rls_connection(request) as conn:
        agent_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM public.alpha_agents WHERE agent_id = $1)",
            agent_id,
        )
        if not agent_exists:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = await conn.fetch(
            """
            SELECT r.id, r.agent_id, r.status, r.trigger_type, r.trace_id,
                   r.started_at, r.completed_at, r.cost_usd, r.error_text,
                   r.workspace_backend, r.workspace_root, r.policy_labels,
                   r.approval_scope, r.retention_class, r.metadata, r.created_at,
                   (
                       SELECT COUNT(*)
                       FROM public.alpha_agent_run_artifacts a
                       WHERE a.run_id = r.id
                   ) AS artifact_count
            FROM public.alpha_agent_runs r
            WHERE r.agent_id = $1
            ORDER BY COALESCE(r.completed_at, r.started_at, r.created_at) DESC,
                     r.created_at DESC
            LIMIT $2
            """,
            agent_id,
            limit,
        )
    return AgentRunListOut(
        count=len(rows), runs=[_agent_run_from_row(row) for row in rows]
    )


@router.post(
    "/agent-runs/{run_id}/workspace/init",
    response_model=AgentRunWorkspaceOut,
)
async def init_agent_run_workspace(
    run_id: UUID,
    request: Request,
) -> AgentRunWorkspaceOut:
    check_scopes(request, "agents.write")
    backend = get_workspace_backend()
    async with rls_connection(request) as conn:
        row = await _load_agent_run_row(conn, run_id)
        manifest = await _ensure_workspace(conn, row, backend=backend)
    usage_bytes = backend.workspace_usage_bytes(
        run_id,
        workspace_root=manifest.workspace_root,
    )
    return _workspace_from_manifest(manifest, usage_bytes=usage_bytes, backend=backend)


@router.get("/agent-runs/{run_id}/workspace", response_model=AgentRunWorkspaceOut)
async def get_agent_run_workspace(
    run_id: UUID,
    request: Request,
) -> AgentRunWorkspaceOut:
    check_scopes(request, "agents.read")
    backend = get_workspace_backend()
    async with rls_connection(request) as conn:
        row = await _load_agent_run_row(conn, run_id)
    workspace_root = str(row["workspace_root"] or "").strip()
    if not workspace_root:
        raise HTTPException(status_code=404, detail="Workspace not initialized")
    try:
        manifest = backend.read_manifest(run_id, workspace_root=workspace_root)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Workspace not initialized"
        ) from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    usage_bytes = backend.workspace_usage_bytes(
        run_id,
        workspace_root=manifest.workspace_root,
    )
    return _workspace_from_manifest(manifest, usage_bytes=usage_bytes, backend=backend)


@router.get("/agent-runs/{run_id}/artifacts", response_model=AgentRunArtifactListOut)
async def list_agent_run_artifacts(
    run_id: UUID,
    request: Request,
) -> AgentRunArtifactListOut:
    check_scopes(request, "agents.read")
    async with rls_connection(request) as conn:
        await _load_agent_run_row(conn, run_id)
        rows = await conn.fetch(
            """
            SELECT id, run_id, relative_path, kind, content_type, size_bytes,
                   sha256, policy_labels, created_at
            FROM public.alpha_agent_run_artifacts
            WHERE run_id = $1
            ORDER BY created_at ASC, id ASC
            """,
            run_id,
        )
    artifacts = [
        AgentRunArtifactOut(
            artifact_id=str(row["id"]),
            run_id=str(row["run_id"]),
            relative_path=row["relative_path"],
            kind=row["kind"],
            content_type=row["content_type"],
            size_bytes=int(row["size_bytes"]),
            created_at=_iso(row["created_at"]) or "",
            sha256=row["sha256"],
            policy_labels=_jsonb_list(row["policy_labels"]),
        )
        for row in rows
    ]
    return AgentRunArtifactListOut(count=len(artifacts), artifacts=artifacts)


@router.get(
    "/agent-runs/{run_id}/artifacts/{artifact_id}/preview",
    response_model=AgentRunArtifactPreviewOut,
)
async def preview_agent_run_artifact(
    run_id: UUID,
    artifact_id: UUID,
    request: Request,
) -> AgentRunArtifactPreviewOut:
    check_scopes(request, "agents.read")
    backend = get_workspace_backend()
    async with rls_connection(request) as conn:
        row = await _load_agent_run_row(conn, run_id)
        artifact_row = await _load_agent_run_artifact_row(conn, run_id, artifact_id)
    workspace_root = str(row["workspace_root"] or "").strip()
    if not workspace_root:
        raise HTTPException(status_code=404, detail="Workspace not initialized")
    retention_expires_at = backend.retention_expires_at(
        row["created_at"],
        row["retention_class"],
    )
    if not _previewable_content_type(str(artifact_row["content_type"] or "")):
        return _artifact_preview_from_record(
            artifact_row,
            WorkspaceArtifactPreview(
                text=None,
                truncated=False,
                preview_bytes=0,
                preview_available=False,
            ),
            approval_scope=row["approval_scope"],
            retention_expires_at=retention_expires_at,
        )
    try:
        backend.assert_within_retention(
            created_at=row["created_at"],
            retention_class=row["retention_class"],
        )
        preview = backend.preview_text(
            run_id,
            artifact_row["relative_path"],
            workspace_root=workspace_root,
        )
    except WorkspaceRetentionExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact content missing") from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _artifact_preview_from_record(
        artifact_row,
        preview,
        approval_scope=row["approval_scope"],
        retention_expires_at=retention_expires_at,
    )


@router.get("/agent-runs/{run_id}/artifacts/{artifact_id}/download")
async def download_agent_run_artifact(
    run_id: UUID,
    artifact_id: UUID,
    request: Request,
) -> Response:
    return await _artifact_binary_response(
        run_id,
        artifact_id,
        request,
        disposition="attachment",
    )


@router.get("/agent-runs/{run_id}/artifacts/{artifact_id}/content")
async def get_agent_run_artifact_content(
    run_id: UUID,
    artifact_id: UUID,
    request: Request,
) -> Response:
    return await _artifact_binary_response(
        run_id,
        artifact_id,
        request,
        disposition="inline",
    )


@router.post("/agent-runs/{run_id}/artifacts", response_model=AgentRunArtifactOut)
async def create_agent_run_artifact(
    run_id: UUID,
    request: Request,
    kind: str = Form(...),
    relative_path: str = Form(...),
    text: str | None = Form(default=None),
    content_type: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
) -> AgentRunArtifactOut:
    check_scopes(request, "agents.write")
    if (text is None and file is None) or (text is not None and file is not None):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of text or file content",
        )

    backend = get_workspace_backend()
    async with rls_connection(request) as conn:
        row = await _load_agent_run_row(conn, run_id)
        manifest = await _ensure_workspace(conn, row, backend=backend)
        try:
            backend.assert_within_retention(
                created_at=row["created_at"],
                retention_class=row["retention_class"],
            )
            if file is not None:
                staged = backend.stage_upload_stream(
                    run_id,
                    relative_path,
                    file.file,
                    kind,
                    content_type=content_type
                    or file.content_type
                    or "application/octet-stream",
                    policy_labels=_jsonb_list(row["policy_labels"]),
                    workspace_root=manifest.workspace_root,
                )
            else:
                staged = backend.stage_text(
                    run_id,
                    relative_path,
                    text or "",
                    kind,
                    content_type=content_type or "text/plain",
                    policy_labels=_jsonb_list(row["policy_labels"]),
                    workspace_root=manifest.workspace_root,
                )
        except WorkspaceRetentionExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except (ValueError, WorkspacePathError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            await _insert_agent_run_artifact(
                conn,
                artifact=staged.record,
                agent_id=row["agent_id"],
            )
            record = backend.commit_staged_artifact(staged)
        except Exception:
            await _delete_agent_run_artifact(conn, staged.record.artifact_id)
            backend.cleanup_staged_artifact(staged)
            raise
        finally:
            if file is not None:
                await file.close()
    return _artifact_from_record(record)


@router.post("/agents/{agent_id}/enable", response_model=AgentOut)
async def enable_agent(agent_id: str, request: Request) -> AgentOut:
    check_scopes(request, "agents.write")
    return await _set_agent_enabled(agent_id, request, enabled=True)


@router.post("/agents/{agent_id}/disable", response_model=AgentOut)
async def disable_agent(agent_id: str, request: Request) -> AgentOut:
    check_scopes(request, "agents.write")
    return await _set_agent_enabled(agent_id, request, enabled=False)


@router.post("/agents/{agent_id}/run", response_model=AgentManualRunOut)
async def run_agent(agent_id: str, request: Request) -> AgentManualRunOut:
    check_scopes(request, "agents.write")
    canonical_id = canonical_agent_id(agent_id)
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            SELECT agent_id, status, enabled, risk_tier, metadata
            FROM public.alpha_agents
            WHERE agent_id = $1
            """,
            canonical_id,
        )
    eligibility = manual_run_eligibility(
        {
            "agent_id": row["agent_id"],
            "status": row["status"],
            "enabled": row["enabled"],
            "risk_tier": row["risk_tier"],
            "metadata": _jsonb(row["metadata"]),
        }
        if row
        else None
    )
    if not eligibility.allowed:
        status_code = 404 if eligibility.reason == "unknown_agent" else 409
        raise HTTPException(status_code=status_code, detail=eligibility.reason)

    result = await run_agent_now(canonical_id, pool=get_pool())
    logger.info(
        "AGENT_MANUAL_RUN agent_id=%s executed=%s run_id=%s",
        agent_id,
        result.executed,
        result.run_id,
    )
    return AgentManualRunOut(
        agent_id=result.agent_id,
        executed=result.executed,
        run_id=str(result.run_id) if result.run_id else None,
        status=result.status,
        trace_id=result.trace_id,
        skipped_reason=result.skipped_reason,
        error_text=result.error_text,
    )


async def _load_agent_run_row(conn, run_id: UUID):
    row = await conn.fetchrow(
        """
        SELECT id, agent_id, created_at, workspace_backend, workspace_root,
               policy_labels, approval_scope, retention_class
        FROM public.alpha_agent_runs
        WHERE id = $1
        """,
        run_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return row


async def _load_agent_run_artifact_row(conn, run_id: UUID, artifact_id: UUID):
    row = await conn.fetchrow(
        """
        SELECT id, run_id, relative_path, kind, content_type
        FROM public.alpha_agent_run_artifacts
        WHERE run_id = $1 AND id = $2
        """,
        run_id,
        artifact_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Agent artifact not found")
    return row


async def _artifact_binary_response(
    run_id: UUID,
    artifact_id: UUID,
    request: Request,
    *,
    disposition: Literal["inline", "attachment"],
) -> Response:
    check_scopes(request, "agents.read")
    backend = get_workspace_backend()
    async with rls_connection(request) as conn:
        row = await _load_agent_run_row(conn, run_id)
        artifact_row = await _load_agent_run_artifact_row(conn, run_id, artifact_id)
    workspace_root = str(row["workspace_root"] or "").strip()
    if not workspace_root:
        raise HTTPException(status_code=404, detail="Workspace not initialized")
    try:
        backend.assert_within_retention(
            created_at=row["created_at"],
            retention_class=row["retention_class"],
        )
        payload = backend.read_bytes(
            run_id,
            artifact_row["relative_path"],
            workspace_root=workspace_root,
        )
    except WorkspaceRetentionExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact content missing") from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    filename = (
        Path(str(artifact_row["relative_path"])).name.replace('"', "") or "artifact"
    )
    content_disposition = (
        "attachment"
        if _raw_access_mode(row["approval_scope"]) == "download_only"
        else disposition
    )
    return Response(
        content=payload,
        media_type=str(artifact_row["content_type"] or "application/octet-stream"),
        headers={
            "Content-Disposition": f'{content_disposition}; filename="{filename}"'
        },
    )


async def _ensure_workspace(conn, row, *, backend) -> WorkspaceManifest:
    try:
        manifest = backend.init_workspace(
            row["id"],
            row["agent_id"],
            _jsonb_list(row["policy_labels"]),
            row["approval_scope"],
            row["retention_class"],
            workspace_root=str(row["workspace_root"] or "").strip() or None,
            created_at=row["created_at"],
        )
    except WorkspacePathError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if (
        row["workspace_root"] != manifest.workspace_root
        or row["workspace_backend"] != manifest.workspace_backend
    ):
        await conn.execute(
            """
            UPDATE public.alpha_agent_runs
            SET workspace_backend = $2,
                workspace_root = $3
            WHERE id = $1
            """,
            row["id"],
            manifest.workspace_backend,
            manifest.workspace_root,
        )
    return manifest


async def _insert_agent_run_artifact(
    conn,
    *,
    artifact: WorkspaceArtifactRecord,
    agent_id: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO public.alpha_agent_run_artifacts
            (id, run_id, agent_id, relative_path, kind, content_type, size_bytes,
             sha256, policy_labels)
        VALUES
            ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb)
        """,
        artifact.artifact_id,
        artifact.run_id,
        agent_id,
        artifact.relative_path,
        artifact.kind,
        artifact.content_type,
        artifact.size_bytes,
        artifact.sha256,
        json.dumps(list(artifact.policy_labels)),
    )


async def _delete_agent_run_artifact(conn, artifact_id: str) -> None:
    await conn.execute(
        "DELETE FROM public.alpha_agent_run_artifacts WHERE id = $1::uuid",
        artifact_id,
    )


async def _set_agent_enabled(
    agent_id: str, request: Request, *, enabled: bool
) -> AgentOut:
    actor = str(getattr(request.state, "user_id", "unknown"))
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            UPDATE public.alpha_agents
            SET enabled = $2,
                status = CASE
                    WHEN $2 THEN
                        CASE WHEN status = 'disabled' THEN 'planned' ELSE status END
                    ELSE 'disabled'
                END,
                metadata = jsonb_set(
                    metadata,
                    CASE
                        WHEN $2 THEN ARRAY['last_enabled_by']
                        ELSE ARRAY['last_disabled_by']
                    END,
                    to_jsonb($3::text),
                    true
                ),
                updated_at = NOW()
            WHERE agent_id = $1
            RETURNING agent_id, display_name, purpose, risk_tier, status, enabled,
                      owner, cadence, launch_label, allowed_skills, allowed_scopes,
                      cost_daily_cap_usd, model_policy, approval_policy, metadata
            """,
            agent_id,
            enabled,
            actor,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    logger.info("AGENT_REGISTRY_SET_ENABLED agent_id=%s enabled=%s", agent_id, enabled)
    return _agent_from_row(row)
