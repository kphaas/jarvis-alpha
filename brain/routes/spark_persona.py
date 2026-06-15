"""Spark persona guardrail routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.db.rls import rls_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.auto_brain import (
    AutoBrainConfigError,
    AutoSparkContextMetadata,
    load_auto_spark_context,
)
from brain.services.spark_personality_memory import (
    PersonalityMemoryKind,
    PersonalityMemorySource,
    archive_personality_memory,
    build_personality_memory_proposals,
    fetch_personality_memory,
    propose_personality_memory_from_note,
    reject_personality_memory_proposal,
    save_personality_memory,
)
from brain.services.spark_persona_guardrails import (
    SparkGuardrailState,
    load_spark_guardrails,
    save_spark_guardrails,
)
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/spark/persona", tags=["spark-persona"])
logger = get_logger("alpha_brain")


class SparkPersonalityMemoryItem(BaseModel):
    id: str
    principal_id: str
    kind: str
    content: str
    source: str
    evidence_ref_hash: str | None = None
    importance_score: float
    approved_by: str
    approved_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SparkPersonalityMemoryProposalModel(BaseModel):
    proposal_id: str
    principal_id: str
    kind: PersonalityMemoryKind
    content: str
    source: PersonalityMemorySource
    reason: str
    confidence: float
    evidence_ref_hash: str | None = None


class SparkPersonalityMemoryScorecard(BaseModel):
    active_count: int
    proposal_count: int
    feedback_phrase_count: int
    kinds_present: list[str]
    missing_core_kinds: list[str]
    readiness: str


class SparkPersonalityMemoryReviewResponse(BaseModel):
    principal_id: str
    active: list[SparkPersonalityMemoryItem]
    proposals: list[SparkPersonalityMemoryProposalModel]
    scorecard: SparkPersonalityMemoryScorecard
    buddy: dict[str, object]


class SparkPersonalityMemoryProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    note: str = Field(min_length=3, max_length=800)


class SparkPersonalityMemoryProposeResponse(BaseModel):
    status: str
    proposal: SparkPersonalityMemoryProposalModel | None = None
    reason: str | None = None


class SparkPersonalityMemoryApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool = True
    proposal_id: str = Field(min_length=8, max_length=64)
    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    kind: PersonalityMemoryKind
    content: str = Field(min_length=1, max_length=500)
    source: PersonalityMemorySource = "spark_approved"
    evidence_ref_hash: str | None = Field(default=None, min_length=64, max_length=64)
    importance_score: float = Field(default=0.8, ge=0.0, le=1.0)


class SparkPersonalityMemoryApproveResponse(BaseModel):
    status: str
    result: dict[str, object]


class SparkPersonalityMemoryArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    memory_id: str = Field(min_length=8, max_length=64)


class SparkPersonalityMemoryArchiveResponse(BaseModel):
    status: str
    result: dict[str, object]


class SparkPersonalityMemoryRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    proposal_id: str = Field(min_length=8, max_length=64)


class SparkPersonalityMemoryRejectResponse(BaseModel):
    status: str
    result: dict[str, object]


@router.get("/auto-context", response_model=AutoSparkContextMetadata)
async def get_spark_auto_context(
    request: Request,
    _: str = Depends(require_auth),
) -> AutoSparkContextMetadata:
    check_scopes(request, "spark.draft")
    try:
        context = load_auto_spark_context()
    except AutoBrainConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail="auto_spark_context_unavailable",
        ) from exc
    logger.info(
        "spark_auto_context_checked",
        extra={
            "event": "spark_auto_context_checked",
            "component": "spark_persona",
            "source_count": context.source_count,
            "rule_count": context.rule_count,
            "body_access": context.body_access,
            "raw_content_returned": context.raw_content_returned,
            "actor_sub": str(getattr(request.state, "user_id", "unknown")),
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return context


@router.get("/guardrails", response_model=SparkGuardrailState)
async def get_spark_guardrails(
    request: Request,
    _: str = Depends(require_auth),
) -> SparkGuardrailState:
    check_scopes(request, "spark.draft")
    try:
        return load_spark_guardrails()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_guardrails_load_failed"
        ) from exc


@router.put("/guardrails", response_model=SparkGuardrailState)
async def put_spark_guardrails(
    request: Request,
    payload: SparkGuardrailState,
    _: str = Depends(require_auth),
) -> SparkGuardrailState:
    check_scopes(request, "admin")
    try:
        saved = save_spark_guardrails(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="spark_guardrails_invalid") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_guardrails_save_failed"
        ) from exc

    logger.info(
        "spark_guardrails_updated",
        extra={
            "event": "spark_guardrails_updated",
            "component": "spark_persona",
            "principal_id": saved.principal_id,
            "active_mode": saved.active_mode,
            "auto_send_enabled": saved.auto_send_enabled,
            "protected_topic_count": len(saved.protected_topics),
            "protected_relationship_count": len(saved.protected_relationships),
            "actor_sub": str(getattr(request.state, "user_id", "unknown")),
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return saved


@router.get("/memory", response_model=SparkPersonalityMemoryReviewResponse)
async def get_spark_personality_memory(
    request: Request,
    principal_id: str = "ken",
    _: str = Depends(require_auth),
) -> SparkPersonalityMemoryReviewResponse:
    check_scopes(request, "admin")
    guardrails = load_spark_guardrails()
    async with rls_connection(request) as conn:
        rows = await fetch_personality_memory(conn, principal_id)
    proposals = build_personality_memory_proposals(
        principal_id=principal_id,
        guardrails=guardrails,
        existing_rows=rows,
    )
    logger.info(
        "spark_personality_memory_reviewed",
        extra={
            "event": "spark_personality_memory_reviewed",
            "component": "spark_persona",
            "principal_id": principal_id,
            "active_count": len(rows),
            "proposal_count": len(proposals),
            "actor_sub": str(getattr(request.state, "user_id", "unknown")),
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return SparkPersonalityMemoryReviewResponse(
        principal_id=principal_id,
        active=[_personality_item(row) for row in rows],
        proposals=[
            SparkPersonalityMemoryProposalModel(**asdict(proposal))
            for proposal in proposals
        ],
        scorecard=_memory_scorecard(rows, proposals),
        buddy={
            "status": "review_ready",
            "proposal_count": len(proposals),
            "feedback_phrase_count": sum(
                1 for proposal in proposals if proposal.source == "spark_feedback"
            ),
        },
    )


@router.post("/memory/propose", response_model=SparkPersonalityMemoryProposeResponse)
async def propose_spark_personality_memory(
    request: Request,
    payload: SparkPersonalityMemoryProposeRequest,
    _: str = Depends(require_auth),
) -> SparkPersonalityMemoryProposeResponse:
    check_scopes(request, "admin")
    try:
        proposal = propose_personality_memory_from_note(
            principal_id=payload.principal_id,
            note=payload.note,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_memory_proposal_failed"
        ) from exc

    actor_sub = str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    logger.info(
        "spark_personality_memory_proposed",
        extra={
            "event": "spark_personality_memory_proposed",
            "component": "spark_persona",
            "principal_id": payload.principal_id,
            "proposed": proposal is not None,
            "proposal_id": proposal.proposal_id if proposal else "",
            "kind": proposal.kind if proposal else "",
            "source": proposal.source if proposal else "",
            "evidence_ref_hash": proposal.evidence_ref_hash if proposal else "",
            "note_length": len(payload.note),
            "actor_sub": actor_sub,
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    if proposal is None:
        return SparkPersonalityMemoryProposeResponse(
            status="not_proposed",
            reason="invalid_or_sensitive_note",
        )
    return SparkPersonalityMemoryProposeResponse(
        status="proposed",
        proposal=SparkPersonalityMemoryProposalModel(**asdict(proposal)),
    )


@router.post("/memory/approve", response_model=SparkPersonalityMemoryApproveResponse)
async def approve_spark_personality_memory(
    request: Request,
    payload: SparkPersonalityMemoryApproveRequest,
    _: str = Depends(require_auth),
) -> SparkPersonalityMemoryApproveResponse:
    check_scopes(request, "admin")
    if not payload.approved:
        raise HTTPException(status_code=400, detail="spark_memory_approval_required")

    approved_by = str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    async with rls_connection(request) as conn:
        result = await save_personality_memory(
            conn,
            principal_id=payload.principal_id,
            kind=payload.kind,
            content=payload.content,
            source=payload.source,
            evidence_ref_hash=payload.evidence_ref_hash,
            approved_by=approved_by,
            importance_score=payload.importance_score,
        )
    logger.info(
        "spark_personality_memory_approved",
        extra={
            "event": "spark_personality_memory_approved",
            "component": "spark_persona",
            "principal_id": payload.principal_id,
            "kind": payload.kind,
            "source": payload.source,
            "saved": result.get("saved"),
            "proposal_id": payload.proposal_id,
            "actor_sub": approved_by,
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return SparkPersonalityMemoryApproveResponse(
        status="saved" if result.get("saved") else "not_saved",
        result=result,
    )


@router.post("/memory/archive", response_model=SparkPersonalityMemoryArchiveResponse)
async def archive_spark_personality_memory(
    request: Request,
    payload: SparkPersonalityMemoryArchiveRequest,
    _: str = Depends(require_auth),
) -> SparkPersonalityMemoryArchiveResponse:
    check_scopes(request, "admin")
    archived_by = str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    try:
        async with rls_connection(request) as conn:
            result = await archive_personality_memory(
                conn,
                principal_id=payload.principal_id,
                memory_id=payload.memory_id,
                archived_by=archived_by,
            )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_memory_archive_failed"
        ) from exc
    logger.info(
        "spark_personality_memory_archived",
        extra={
            "event": "spark_personality_memory_archived",
            "component": "spark_persona",
            "principal_id": payload.principal_id,
            "memory_id": payload.memory_id,
            "archived": result.get("archived"),
            "actor_sub": archived_by,
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return SparkPersonalityMemoryArchiveResponse(
        status="archived" if result.get("archived") else "not_archived",
        result=result,
    )


@router.post("/memory/reject", response_model=SparkPersonalityMemoryRejectResponse)
async def reject_spark_personality_memory(
    request: Request,
    payload: SparkPersonalityMemoryRejectRequest,
    _: str = Depends(require_auth),
) -> SparkPersonalityMemoryRejectResponse:
    check_scopes(request, "admin")
    rejected_by = str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    try:
        result = reject_personality_memory_proposal(
            principal_id=payload.principal_id,
            proposal_id=payload.proposal_id,
            rejected_by=rejected_by,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_memory_reject_failed"
        ) from exc
    logger.info(
        "spark_personality_memory_proposal_rejected",
        extra={
            "event": "spark_personality_memory_proposal_rejected",
            "component": "spark_persona",
            "principal_id": payload.principal_id,
            "proposal_id": payload.proposal_id,
            "rejected": result.get("rejected"),
            "actor_sub": rejected_by,
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return SparkPersonalityMemoryRejectResponse(
        status="rejected" if result.get("rejected") else "not_rejected",
        result=result,
    )


def _personality_item(row: dict[str, object]) -> SparkPersonalityMemoryItem:
    return SparkPersonalityMemoryItem(
        id=str(row["id"]),
        principal_id=str(row["principal_id"]),
        kind=str(row["kind"]),
        content=str(row["content"]),
        source=str(row["source"]),
        evidence_ref_hash=(
            str(row["evidence_ref_hash"]) if row.get("evidence_ref_hash") else None
        ),
        importance_score=float(row["importance_score"]),
        approved_by=str(row["approved_by"]),
        approved_at=_iso(row.get("approved_at")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _memory_scorecard(
    rows: list[dict[str, object]],
    proposals: tuple[object, ...],
) -> SparkPersonalityMemoryScorecard:
    kinds_present = sorted({str(row.get("kind") or "") for row in rows if row})
    proposal_count = len(proposals)
    feedback_phrase_count = sum(
        1
        for proposal in proposals
        if getattr(proposal, "source", None) == "spark_feedback"
    )
    core_kinds = {"voice", "avoid", "phrase", "relationship", "style"}
    missing = sorted(core_kinds.difference(kinds_present))
    active_count = len(rows)
    if active_count >= 8 and len(missing) <= 1:
        readiness = "strong"
    elif active_count >= 3 or proposal_count:
        readiness = "needs_review"
    else:
        readiness = "thin"
    return SparkPersonalityMemoryScorecard(
        active_count=active_count,
        proposal_count=proposal_count,
        feedback_phrase_count=feedback_phrase_count,
        kinds_present=kinds_present,
        missing_core_kinds=missing,
        readiness=readiness,
    )


def _iso(value: object) -> str | None:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value) if value else None
