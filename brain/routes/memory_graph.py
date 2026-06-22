from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.db.rls import platform_admin_connection, rls_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger


logger = get_logger("alpha_brain")
router = APIRouter(prefix="/v1/memory", tags=["memory-graph"])


class MemoryGraphNode(BaseModel):
    id: str
    node_type: str
    label_hash: str
    label_preview: str
    external_ref_type: str | None = None
    external_ref_id: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    source: str
    confidence: float
    valid_from: str | None = None
    valid_to: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryGraphEdge(BaseModel):
    id: str
    from_node_id: str
    to_node_id: str
    edge_type: str
    properties: dict[str, Any] = Field(default_factory=dict)
    source: str
    confidence: float
    valid_from: str | None = None
    valid_to: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryGraphResponse(BaseModel):
    status: Literal["ok"] = "ok"
    principal_id: str
    as_of: str | None = None
    nodes: list[MemoryGraphNode] = Field(default_factory=list)
    edges: list[MemoryGraphEdge] = Field(default_factory=list)


class MemoryGraphHistoryEvent(BaseModel):
    id: str
    object_type: Literal["node", "edge"]
    operation: str
    proposal_id: str | None = None
    approval_queue_id: str | None = None
    actor: str
    source_surface: str
    reason: str | None = None
    created_at: str | None = None


class MemoryGraphHistoryResponse(BaseModel):
    status: Literal["ok"] = "ok"
    principal_id: str
    object_id: str
    events: list[MemoryGraphHistoryEvent] = Field(default_factory=list)


class MemoryGraphHealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    node_count: int = 0
    edge_count: int = 0
    active_node_count: int = 0
    active_edge_count: int = 0
    open_proposals: int = 0
    stale_proposals: int = 0
    audit_rows: int = 0
    last_activity_at: str | None = None


class MemoryGraphProposalItem(BaseModel):
    proposal_id: str
    principal_id: str
    proposed_action: str
    object_type: Literal["node", "edge"]
    status: str
    approval_queue_id: str | None = None
    approval_status: str | None = None
    approval_expires_at: str | None = None
    parameters_hash: str
    source_surface: str
    created_by: str
    executed_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    executed_at: str | None = None


class MemoryGraphProposalsResponse(BaseModel):
    status: Literal["ok"] = "ok"
    state: str
    proposals: list[MemoryGraphProposalItem] = Field(default_factory=list)


class MemoryGraphProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str | None = Field(default=None, min_length=1, max_length=128)
    proposed_action: Literal[
        "create_node",
        "create_edge",
        "archive_node",
        "archive_edge",
    ]
    object_type: Literal["node", "edge"]
    payload: dict[str, Any] = Field(default_factory=dict)
    source_surface: str = Field(default="helm", min_length=2, max_length=80)
    reason: str | None = Field(default=None, max_length=300)


class MemoryGraphProposalResponse(BaseModel):
    status: Literal["queued", "not_queued"]
    result: dict[str, Any]


class MemoryGraphExecuteResponse(BaseModel):
    status: str
    proposal_id: str
    result: dict[str, Any]


@router.get("/graph", response_model=MemoryGraphResponse)
async def get_memory_graph(
    request: Request,
    as_of: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _user_id: str = Depends(require_auth),
) -> MemoryGraphResponse:
    uid = _request_user_uuid(request)
    async with rls_connection(request) as conn:
        payload = _json_result(
            await conn.fetchval(
                "SELECT public.list_memory_graph_current($1::uuid, $2, $3)",
                str(uid),
                as_of,
                limit,
            )
        )
    return _graph_response(payload)


@router.get("/graph/history/{object_id}", response_model=MemoryGraphHistoryResponse)
async def get_memory_graph_history(
    object_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    _user_id: str = Depends(require_auth),
) -> MemoryGraphHistoryResponse:
    uid = _request_user_uuid(request)
    async with rls_connection(request) as conn:
        payload = _json_result(
            await conn.fetchval(
                "SELECT public.list_memory_graph_history($1::uuid, $2::uuid, $3)",
                str(uid),
                str(object_id),
                limit,
            )
        )
    return _history_response(payload)


@router.get(
    "/admin/users/{principal_id}/graph",
    response_model=MemoryGraphResponse,
)
async def get_memory_admin_user_graph(
    principal_id: str,
    request: Request,
    as_of: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _user_id: str = Depends(require_auth),
) -> MemoryGraphResponse:
    check_scopes(request, "memory.read", "admin")
    principal_uuid = _principal_uuid(principal_id)
    async with platform_admin_connection(
        source="http",
        audit_actor=_review_actor(request),
    ) as conn:
        payload = _json_result(
            await conn.fetchval(
                "SELECT public.list_memory_graph_current($1::uuid, $2, $3)",
                str(principal_uuid),
                as_of,
                limit,
            )
        )
    return _graph_response(payload)


@router.get("/admin/graph/health", response_model=MemoryGraphHealthResponse)
async def get_memory_graph_health(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> MemoryGraphHealthResponse:
    check_scopes(request, "memory.read", "admin")
    async with platform_admin_connection(
        source="http",
        audit_actor=_review_actor(request),
    ) as conn:
        payload = _json_result(
            await conn.fetchval("SELECT public.memory_graph_health()")
        )
    return MemoryGraphHealthResponse(**_normalize_health(payload))


@router.get("/admin/graph/proposals", response_model=MemoryGraphProposalsResponse)
async def list_memory_graph_proposals(
    request: Request,
    principal_id: str | None = Query(default=None),
    state: Literal["open", "all", "pending_review", "queued", "executed", "stale"] = (
        Query(default="open")
    ),
    limit: int = Query(default=50, ge=1, le=200),
    _user_id: str = Depends(require_auth),
) -> MemoryGraphProposalsResponse:
    check_scopes(request, "memory.read", "admin")
    principal_uuid = _principal_uuid(principal_id) if principal_id else None
    async with platform_admin_connection(
        source="http",
        audit_actor=_review_actor(request),
    ) as conn:
        payload = _json_result(
            await conn.fetchval(
                "SELECT public.list_memory_graph_proposals($1::uuid, $2, $3)",
                str(principal_uuid) if principal_uuid else None,
                state,
                limit,
            )
        )
    return _proposals_response(payload)


@router.post("/graph/proposals", response_model=MemoryGraphProposalResponse)
async def propose_memory_graph_write(
    body: MemoryGraphProposalRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> MemoryGraphProposalResponse:
    check_scopes(request, "memory.write", "admin")
    principal_uuid = (
        _principal_uuid(body.principal_id)
        if body.principal_id
        else _request_user_uuid(request)
    )
    async with rls_connection(request) as conn:
        payload = _json_result(
            await conn.fetchval(
                """
                SELECT public.propose_memory_graph_write(
                    $1::uuid,
                    $2,
                    $3,
                    $4::jsonb,
                    $5,
                    $6,
                    $7
                )
                """,
                str(principal_uuid),
                body.proposed_action,
                body.object_type,
                json.dumps(body.payload, sort_keys=True),
                body.source_surface,
                _review_actor(request),
                body.reason,
            )
        )
    status = str(payload.get("status") or "not_queued")
    logger.info(
        "MEMORY_GRAPH_PROPOSAL_CREATED",
        extra={
            "event": "MEMORY_GRAPH_PROPOSAL_CREATED",
            "principal_id": str(principal_uuid),
            "status": status,
            "proposed_action": body.proposed_action,
            "object_type": body.object_type,
            "proposal_id": payload.get("proposal_id"),
        },
    )
    return MemoryGraphProposalResponse(
        status="queued" if status == "queued" else "not_queued",
        result=payload,
    )


@router.post(
    "/graph/proposals/{proposal_id}/execute",
    response_model=MemoryGraphExecuteResponse,
)
async def execute_memory_graph_proposal(
    proposal_id: UUID,
    request: Request,
    x_approval_token: str = Header(alias="X-Approval-Token"),
    _user_id: str = Depends(require_auth),
) -> MemoryGraphExecuteResponse:
    check_scopes(request, "memory.write", "admin")
    approval_queue_id = _uuid_header(x_approval_token, "X-Approval-Token")
    actor = _review_actor(request)
    async with rls_connection(request) as conn:
        payload = _json_result(
            await conn.fetchval(
                "SELECT public.execute_memory_graph_proposal($1::uuid, $2::uuid, $3)",
                str(proposal_id),
                str(approval_queue_id),
                actor,
            )
        )
    status = str(payload.get("status") or "unknown")
    logger.info(
        "MEMORY_GRAPH_PROPOSAL_EXECUTED",
        extra={
            "event": "MEMORY_GRAPH_PROPOSAL_EXECUTED",
            "proposal_id": str(proposal_id),
            "approval_queue_id": str(approval_queue_id),
            "status": status,
            "object_type": payload.get("object_type"),
            "operation": payload.get("operation"),
        },
    )
    return MemoryGraphExecuteResponse(
        status=status,
        proposal_id=str(proposal_id),
        result=payload,
    )


def _graph_response(payload: dict[str, Any]) -> MemoryGraphResponse:
    return MemoryGraphResponse(
        principal_id=str(payload.get("principal_id") or ""),
        as_of=_optional_str(payload.get("as_of")),
        nodes=[
            MemoryGraphNode(**_normalize_node(row))
            for row in _list(payload.get("nodes"))
        ],
        edges=[
            MemoryGraphEdge(**_normalize_edge(row))
            for row in _list(payload.get("edges"))
        ],
    )


def _history_response(payload: dict[str, Any]) -> MemoryGraphHistoryResponse:
    return MemoryGraphHistoryResponse(
        principal_id=str(payload.get("principal_id") or ""),
        object_id=str(payload.get("object_id") or ""),
        events=[
            MemoryGraphHistoryEvent(**_normalize_history_event(row))
            for row in _list(payload.get("events"))
        ],
    )


def _proposals_response(payload: dict[str, Any]) -> MemoryGraphProposalsResponse:
    return MemoryGraphProposalsResponse(
        state=str(payload.get("state") or "open"),
        proposals=[
            MemoryGraphProposalItem(**_normalize_proposal(row))
            for row in _list(payload.get("proposals"))
        ],
    )


def _normalize_node(row: object) -> dict[str, Any]:
    data = _dict(row)
    return {
        "id": str(data.get("id") or ""),
        "node_type": str(data.get("node_type") or "other"),
        "label_hash": str(data.get("label_hash") or ""),
        "label_preview": str(data.get("label_preview") or ""),
        "external_ref_type": _optional_str(data.get("external_ref_type")),
        "external_ref_id": _optional_str(data.get("external_ref_id")),
        "properties": _dict(data.get("properties")),
        "source": str(data.get("source") or "operator"),
        "confidence": float(data.get("confidence") or 0),
        "valid_from": _optional_str(data.get("valid_from")),
        "valid_to": _optional_str(data.get("valid_to")),
        "created_at": _optional_str(data.get("created_at")),
        "updated_at": _optional_str(data.get("updated_at")),
    }


def _normalize_edge(row: object) -> dict[str, Any]:
    data = _dict(row)
    return {
        "id": str(data.get("id") or ""),
        "from_node_id": str(data.get("from_node_id") or ""),
        "to_node_id": str(data.get("to_node_id") or ""),
        "edge_type": str(data.get("edge_type") or "related_to"),
        "properties": _dict(data.get("properties")),
        "source": str(data.get("source") or "operator"),
        "confidence": float(data.get("confidence") or 0),
        "valid_from": _optional_str(data.get("valid_from")),
        "valid_to": _optional_str(data.get("valid_to")),
        "created_at": _optional_str(data.get("created_at")),
        "updated_at": _optional_str(data.get("updated_at")),
    }


def _normalize_history_event(row: object) -> dict[str, Any]:
    data = _dict(row)
    return {
        "id": str(data.get("id") or ""),
        "object_type": str(data.get("object_type") or "node"),
        "operation": str(data.get("operation") or "unknown"),
        "proposal_id": _optional_str(data.get("proposal_id")),
        "approval_queue_id": _optional_str(data.get("approval_queue_id")),
        "actor": str(data.get("actor") or "unknown"),
        "source_surface": str(data.get("source_surface") or "unknown"),
        "reason": _optional_str(data.get("reason")),
        "created_at": _optional_str(data.get("created_at")),
    }


def _normalize_proposal(row: object) -> dict[str, Any]:
    data = _dict(row)
    return {
        "proposal_id": str(data.get("proposal_id") or ""),
        "principal_id": str(data.get("principal_id") or ""),
        "proposed_action": str(data.get("proposed_action") or "unknown"),
        "object_type": str(data.get("object_type") or "node"),
        "status": str(data.get("status") or "unknown"),
        "approval_queue_id": _optional_str(data.get("approval_queue_id")),
        "approval_status": _optional_str(data.get("approval_status")),
        "approval_expires_at": _optional_str(data.get("approval_expires_at")),
        "parameters_hash": str(data.get("parameters_hash") or ""),
        "source_surface": str(data.get("source_surface") or "unknown"),
        "created_by": str(data.get("created_by") or "unknown"),
        "executed_by": _optional_str(data.get("executed_by")),
        "created_at": _optional_str(data.get("created_at")),
        "updated_at": _optional_str(data.get("updated_at")),
        "executed_at": _optional_str(data.get("executed_at")),
    }


def _normalize_health(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_count": int(payload.get("node_count") or 0),
        "edge_count": int(payload.get("edge_count") or 0),
        "active_node_count": int(payload.get("active_node_count") or 0),
        "active_edge_count": int(payload.get("active_edge_count") or 0),
        "open_proposals": int(payload.get("open_proposals") or 0),
        "stale_proposals": int(payload.get("stale_proposals") or 0),
        "audit_rows": int(payload.get("audit_rows") or 0),
        "last_activity_at": _optional_str(payload.get("last_activity_at")),
    }


def _request_user_uuid(request: Request) -> UUID:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return _principal_uuid(str(user_id))


def _principal_uuid(principal_id: str | None) -> UUID:
    if not principal_id:
        raise HTTPException(status_code=400, detail="principal_id_required")
    try:
        return UUID(str(principal_id))
    except ValueError:
        return uuid5(NAMESPACE_DNS, str(principal_id))


def _review_actor(request: Request) -> str:
    return (
        str(getattr(request.state, "user_sub", None) or "")
        or str(getattr(request.state, "user_id", None) or "")
        or "unknown"
    )


def _uuid_header(value: str, header_name: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{header_name} must be an approval queue UUID",
        ) from exc


def _json_result(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {"value": loaded}
    return {"value": value}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
