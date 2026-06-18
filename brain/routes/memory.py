from __future__ import annotations

from typing import Literal
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.db.rls import rls_connection
from brain.memory.memory import MemoryService, SEMANTIC_CAP
from brain.memory.semantic_commands import (
    MemoryCategory,
    MemoryFactValidationError,
    sanitize_semantic_fact,
)
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger

router = APIRouter()
logger = get_logger("alpha_brain")


class SemanticMemoryItem(BaseModel):
    id: str
    fact: str
    category: str
    source: str
    provenance: dict[str, object] = Field(default_factory=dict)
    review_status: Literal["active", "pending_review", "rejected", "archived"] = (
        "active"
    )
    review_reason: str | None = None
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class WorkingMemoryItem(BaseModel):
    id: str
    session_id: str
    summary: str
    role: str
    importance_score: float
    created_at: str | None = None


class MemorySummaryResponse(BaseModel):
    status: Literal["ok"] = "ok"
    user_id: str
    semantic_cap: int = SEMANTIC_CAP
    semantic_count: int
    semantic_review_count: int = 0
    episodic_count: int
    working_count: int
    semantic: list[SemanticMemoryItem]
    working: list[WorkingMemoryItem]


class MemoryTelemetryMetrics(BaseModel):
    total_semantic: int = 0
    active_semantic: int = 0
    pending_review: int = 0
    rejected: int = 0
    archived: int = 0
    semantic_saves_24h: int = 0
    semantic_saves_7d: int = 0
    review_required_24h: int = 0
    memory_buddy_events_7d: int = 0
    unread_memory_buddy_events: int = 0
    high_priority_buddy_events: int = 0
    dream_proposals_7d: int = 0
    dream_reviewed_writes_open: int = 0
    dream_proposals_queued: int = 0
    dream_informational_open: int = 0
    dream_approved_waiting_execution: int = 0
    dream_proposals_executed: int = 0
    dream_proposals_reverted: int = 0
    stale_dream_reviewed_writes: int = 0
    dream_approval_mismatch_count: int = 0
    dream_executed_without_ledger: int = 0


class MemoryTelemetryCount(BaseModel):
    label: str
    count: int


class MemoryTelemetrySemanticEvent(BaseModel):
    id: str
    category: str
    review_status: Literal["active", "pending_review", "rejected", "archived"]
    review_reason: str | None = None
    source_surface: str
    source_action: str
    buddy_event_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryTelemetryBuddyEvent(BaseModel):
    id: str
    event_type: str
    title: str
    priority: int
    read: bool
    source: str | None = None
    memory_id: str | None = None
    created_at: str | None = None


class MemoryTelemetryDreamProposal(BaseModel):
    proposal_id: str
    proposed_action: str
    executable: bool
    status: str
    approval_queue_id: str | None = None
    approval_status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryTelemetryResponse(BaseModel):
    status: Literal["ok"] = "ok"
    user_id: str
    metrics: MemoryTelemetryMetrics
    source_surfaces_7d: list[MemoryTelemetryCount]
    categories_7d: list[MemoryTelemetryCount]
    recent_semantic_saves: list[MemoryTelemetrySemanticEvent]
    recent_buddy_events: list[MemoryTelemetryBuddyEvent]
    recent_dream_proposals: list[MemoryTelemetryDreamProposal] = Field(
        default_factory=list
    )


class SaveSemanticMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact: str = Field(min_length=3, max_length=1000)
    category: MemoryCategory = "project"
    source_surface: str | None = Field(default=None, min_length=2, max_length=80)
    source_thread_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_message_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_action: str | None = Field(default=None, min_length=2, max_length=80)


class SaveSemanticMemoryResponse(BaseModel):
    status: Literal["saved", "not_saved"]
    result: dict[str, object]


class ReviewSemanticMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject", "archive"]
    note: str | None = Field(default=None, max_length=300)


class ReviewSemanticMemoryResponse(BaseModel):
    status: Literal["reviewed", "not_found", "error"]
    result: dict[str, object]


class ForgetMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str | None = Field(default=None, min_length=2, max_length=160)
    working_only: bool = True


class ForgetMemoryResponse(BaseModel):
    status: Literal["forgot"]
    deleted: int
    scope: Literal["topic", "working"]


@router.get("/v1/memory")
async def get_memory_legacy(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> MemorySummaryResponse:
    return await get_memory_summary(
        request=request,
        semantic_limit=100,
        working_limit=25,
    )


@router.get("/v1/memory/summary", response_model=MemorySummaryResponse)
async def get_memory_summary(
    request: Request,
    semantic_limit: int = Query(default=100, ge=1, le=100),
    working_limit: int = Query(default=25, ge=1, le=100),
    _user_id: str = Depends(require_auth),
) -> MemorySummaryResponse:
    uid = _request_user_uuid(request)
    async with rls_connection(request) as conn:
        snapshot = await MemoryService().summarize(
            conn=conn,
            user_id=uid,
            semantic_limit=semantic_limit,
            working_limit=working_limit,
        )
    return MemorySummaryResponse(
        user_id=str(uid),
        semantic_count=snapshot["semantic_count"],
        semantic_review_count=snapshot["semantic_review_count"],
        episodic_count=snapshot["episodic_count"],
        working_count=snapshot["working_count"],
        semantic=[_semantic_item(row) for row in snapshot["semantic"]],
        working=[_working_item(row) for row in snapshot["working"]],
    )


@router.get("/v1/memory/telemetry", response_model=MemoryTelemetryResponse)
async def get_memory_telemetry(
    request: Request,
    recent_limit: int = Query(default=20, ge=1, le=50),
    _user_id: str = Depends(require_auth),
) -> MemoryTelemetryResponse:
    uid = _request_user_uuid(request)
    async with rls_connection(request) as conn:
        telemetry = await MemoryService().telemetry(
            conn=conn,
            user_id=uid,
            recent_limit=recent_limit,
        )
    semantic_metrics = _dict_value(telemetry.get("semantic_metrics"))
    buddy_metrics = _dict_value(telemetry.get("buddy_metrics"))
    proposal_metrics = _dict_value(telemetry.get("proposal_metrics"))
    return MemoryTelemetryResponse(
        user_id=str(uid),
        metrics=MemoryTelemetryMetrics(
            **{
                **semantic_metrics,
                **buddy_metrics,
                **proposal_metrics,
            }
        ),
        source_surfaces_7d=[
            _telemetry_count(row)
            for row in _list_of_dicts(telemetry.get("source_surfaces_7d"))
        ],
        categories_7d=[
            _telemetry_count(row)
            for row in _list_of_dicts(telemetry.get("categories_7d"))
        ],
        recent_semantic_saves=[
            _telemetry_semantic_event(row)
            for row in _list_of_dicts(telemetry.get("recent_semantic_saves"))
        ],
        recent_buddy_events=[
            _telemetry_buddy_event(row)
            for row in _list_of_dicts(telemetry.get("recent_buddy_events"))
        ],
        recent_dream_proposals=[
            _telemetry_dream_proposal(row)
            for row in _list_of_dicts(telemetry.get("recent_dream_proposals"))
        ],
    )


@router.post("/v1/memory/semantic", response_model=SaveSemanticMemoryResponse)
async def save_semantic_memory(
    body: SaveSemanticMemoryRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> SaveSemanticMemoryResponse:
    check_scopes(request, "memory.write", "admin")
    try:
        fact = sanitize_semantic_fact(body.fact)
    except MemoryFactValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    uid = _request_user_uuid(request)
    async with rls_connection(request) as conn:
        result = await MemoryService().save_semantic(
            conn=conn,
            user_id=uid,
            fact=fact,
            category=body.category,
            provenance=_save_provenance(request, body),
        )
    logger.info(
        "MEMORY_EXPLICIT_SAVE",
        extra={
            "event": "MEMORY_EXPLICIT_SAVE",
            "user_id": str(uid),
            "category": body.category,
            "saved": result.get("saved"),
            "review_required": result.get("review_required"),
        },
    )
    return SaveSemanticMemoryResponse(
        status="saved" if result.get("saved") else "not_saved",
        result=result,
    )


@router.post(
    "/v1/memory/semantic/{memory_id}/review",
    response_model=ReviewSemanticMemoryResponse,
)
async def review_semantic_memory(
    memory_id: UUID,
    body: ReviewSemanticMemoryRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> ReviewSemanticMemoryResponse:
    check_scopes(request, "memory.write", "admin")
    uid = _request_user_uuid(request)
    async with rls_connection(request) as conn:
        result = await MemoryService().review_semantic(
            conn=conn,
            user_id=uid,
            memory_id=memory_id,
            action=body.action,
            reviewed_by=_review_actor(request),
            note=body.note,
        )
    status = str(result.get("status") or "error")
    logger.info(
        "MEMORY_SEMANTIC_REVIEW",
        extra={
            "event": "MEMORY_SEMANTIC_REVIEW",
            "user_id": str(uid),
            "memory_id": str(memory_id),
            "action": body.action,
            "status": status,
        },
    )
    if status not in {"reviewed", "not_found", "error"}:
        status = "error"
    return ReviewSemanticMemoryResponse(status=status, result=result)


@router.post("/v1/memory/forget", response_model=ForgetMemoryResponse)
async def forget_memory(
    body: ForgetMemoryRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> ForgetMemoryResponse:
    check_scopes(request, "memory.write", "admin")
    uid = _request_user_uuid(request)
    memory = MemoryService()
    async with rls_connection(request) as conn:
        if body.topic:
            deleted = await memory.forget_by_topic(conn, uid, body.topic.strip())
            scope: Literal["topic", "working"] = "topic"
        elif body.working_only:
            deleted = await memory.forget_working(conn, uid)
            scope = "working"
        else:
            raise HTTPException(
                status_code=400,
                detail="topic_required_unless_working_only",
            )
    logger.info(
        "MEMORY_FORGET",
        extra={
            "event": "MEMORY_FORGET",
            "user_id": str(uid),
            "scope": scope,
            "deleted": deleted,
        },
    )
    return ForgetMemoryResponse(status="forgot", deleted=deleted, scope=scope)


def _request_user_uuid(request: Request) -> UUID:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return UUID(str(user_id))
    except ValueError:
        return uuid5(NAMESPACE_DNS, str(user_id))


def _save_provenance(
    request: Request,
    body: SaveSemanticMemoryRequest,
) -> dict[str, object]:
    provenance: dict[str, object] = {
        "source_surface": body.source_surface or "memory_api",
        "source_route": str(getattr(request.url, "path", "") or "/v1/memory/semantic"),
        "source_action": body.source_action or "explicit_save",
        "actor_type": str(getattr(request.state, "actor_type", "user") or "user"),
        "actor_role": str(getattr(request.state, "role", "user") or "user"),
    }
    if body.source_thread_id:
        provenance["source_thread_id"] = body.source_thread_id
    if body.source_message_id:
        provenance["source_message_id"] = body.source_message_id
    return provenance


def _review_actor(request: Request) -> str:
    return (
        str(getattr(request.state, "user_sub", None) or "")
        or str(getattr(request.state, "user_id", None) or "")
        or "unknown"
    )


def _semantic_item(row: dict) -> SemanticMemoryItem:
    return SemanticMemoryItem(
        id=str(row["id"]),
        fact=str(row["fact"]),
        category=str(row["category"]),
        source=str(row["source"]),
        provenance=_dict_value(row.get("provenance")),
        review_status=_review_status(row.get("review_status")),
        review_reason=_optional_str(row.get("review_reason")),
        reviewed_at=_iso(row.get("reviewed_at")),
        reviewed_by=_optional_str(row.get("reviewed_by")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _working_item(row: dict) -> WorkingMemoryItem:
    return WorkingMemoryItem(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        summary=str(row["summary"]),
        role=str(row["role"]),
        importance_score=float(row["importance_score"]),
        created_at=_iso(row.get("created_at")),
    )


def _telemetry_count(row: dict) -> MemoryTelemetryCount:
    return MemoryTelemetryCount(
        label=str(row.get("label") or "unknown"),
        count=int(row.get("count") or 0),
    )


def _telemetry_semantic_event(row: dict) -> MemoryTelemetrySemanticEvent:
    return MemoryTelemetrySemanticEvent(
        id=str(row.get("id") or ""),
        category=str(row.get("category") or "unknown"),
        review_status=_review_status(row.get("review_status")),
        review_reason=_optional_str(row.get("review_reason")),
        source_surface=str(row.get("source_surface") or "unknown"),
        source_action=str(row.get("source_action") or "unknown"),
        buddy_event_id=_optional_str(row.get("buddy_event_id")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _telemetry_buddy_event(row: dict) -> MemoryTelemetryBuddyEvent:
    return MemoryTelemetryBuddyEvent(
        id=str(row.get("id") or ""),
        event_type=str(row.get("event_type") or "system"),
        title=str(row.get("title") or "Memory event"),
        priority=int(row.get("priority") or 0),
        read=bool(row.get("read")),
        source=_optional_str(row.get("source")),
        memory_id=_optional_str(row.get("memory_id")),
        created_at=_iso(row.get("created_at")),
    )


def _telemetry_dream_proposal(row: dict) -> MemoryTelemetryDreamProposal:
    return MemoryTelemetryDreamProposal(
        proposal_id=str(row.get("proposal_id") or ""),
        proposed_action=str(row.get("proposed_action") or "unknown"),
        executable=bool(row.get("executable")),
        status=str(row.get("status") or "unknown"),
        approval_queue_id=_optional_str(row.get("approval_queue_id")),
        approval_status=_optional_str(row.get("approval_status")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _iso(value: object) -> str | None:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value) if value else None


def _optional_str(value: object) -> str | None:
    return str(value) if value else None


def _dict_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _review_status(
    value: object,
) -> Literal["active", "pending_review", "rejected", "archived"]:
    if isinstance(value, str) and value in {
        "active",
        "pending_review",
        "rejected",
        "archived",
    }:
        return value
    return "active"
