from __future__ import annotations

import re
from typing import Literal
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.db.rls import rls_connection
from brain.memory.memory import MemoryService, SEMANTIC_CAP
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger

router = APIRouter()
logger = get_logger("alpha_brain")

MemoryCategory = Literal[
    "preference",
    "person",
    "project",
    "constraint",
    "health",
    "child_profile",
]

_CONTROL_TEXT = re.compile(
    r"\b(ignore|disregard|override|bypass)\b.{0,80}\b("
    r"system|developer|previous|prior|instruction|policy|safety|guardrail"
    r")\b",
    re.IGNORECASE,
)
_SECRET_TEXT = re.compile(
    r"\b(api[_ -]?key|bearer token|password|private key|secret)\b",
    re.IGNORECASE,
)


class SemanticMemoryItem(BaseModel):
    id: str
    fact: str
    category: str
    source: str
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
    episodic_count: int
    working_count: int
    semantic: list[SemanticMemoryItem]
    working: list[WorkingMemoryItem]


class SaveSemanticMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact: str = Field(min_length=3, max_length=1000)
    category: MemoryCategory = "project"


class SaveSemanticMemoryResponse(BaseModel):
    status: Literal["saved", "not_saved"]
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
    return await get_memory_summary(request=request)


@router.get("/v1/memory/summary", response_model=MemorySummaryResponse)
async def get_memory_summary(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> MemorySummaryResponse:
    uid = _request_user_uuid(request)
    async with rls_connection(request) as conn:
        snapshot = await MemoryService().summarize(conn=conn, user_id=uid)
    return MemorySummaryResponse(
        user_id=str(uid),
        semantic_count=snapshot["semantic_count"],
        episodic_count=snapshot["episodic_count"],
        working_count=snapshot["working_count"],
        semantic=[_semantic_item(row) for row in snapshot["semantic"]],
        working=[_working_item(row) for row in snapshot["working"]],
    )


@router.post("/v1/memory/semantic", response_model=SaveSemanticMemoryResponse)
async def save_semantic_memory(
    body: SaveSemanticMemoryRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> SaveSemanticMemoryResponse:
    check_scopes(request, "memory.write", "admin")
    fact = _sanitize_fact(body.fact)
    uid = _request_user_uuid(request)
    async with rls_connection(request) as conn:
        result = await MemoryService().save_semantic(
            conn=conn,
            user_id=uid,
            fact=fact,
            category=body.category,
        )
    logger.info(
        "MEMORY_EXPLICIT_SAVE",
        extra={
            "event": "MEMORY_EXPLICIT_SAVE",
            "user_id": str(uid),
            "category": body.category,
            "saved": result.get("saved"),
        },
    )
    return SaveSemanticMemoryResponse(
        status="saved" if result.get("saved") else "not_saved",
        result=result,
    )


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


def _sanitize_fact(fact: str) -> str:
    normalized = " ".join(fact.strip().split())
    if _CONTROL_TEXT.search(normalized):
        raise HTTPException(status_code=422, detail="memory_fact_rejected_control_text")
    if _SECRET_TEXT.search(normalized):
        raise HTTPException(status_code=422, detail="memory_fact_rejected_secret_text")
    return normalized


def _semantic_item(row: dict) -> SemanticMemoryItem:
    return SemanticMemoryItem(
        id=str(row["id"]),
        fact=str(row["fact"]),
        category=str(row["category"]),
        source=str(row["source"]),
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


def _iso(value: object) -> str | None:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value) if value else None
