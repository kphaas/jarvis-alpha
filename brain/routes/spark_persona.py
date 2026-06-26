"""Spark persona guardrail routes."""

from __future__ import annotations
import json
from dataclasses import asdict
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.db.rls import rls_connection
from brain.memory.memory import MemoryService
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
from brain.services.spark_memory_router import (
    SparkMemoryRoutePlan,
    plan_spark_memory_route,
)
from brain.services.spark_target_memory import (
    SparkTargetMemoryProposal,
    TargetMemoryKind,
    TargetMemorySource,
    archive_target_memory,
    fetch_target_memory,
    list_target_memory_proposals,
    propose_target_memory_from_note,
    reject_target_memory_proposal,
    save_target_memory,
)
from brain.services.spark_voice_ingest import (
    SparkApprovedSourceRecord,
    load_approved_voice_sources,
)
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/spark/persona", tags=["spark-persona"])
logger = get_logger("alpha_brain")
SPARK_PERSONALITY_MEMORY_REVIEW_LIMIT = 96


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
    feedback_lesson_count: int
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


class SparkTargetMemoryItem(BaseModel):
    id: str
    principal_id: str
    target_ref_hash: str
    target_label: str
    kind: str
    content: str
    source: str
    evidence_ref_hash: str | None = None
    importance_score: float
    approved_by: str
    approved_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SparkTargetMemoryProposalModel(BaseModel):
    proposal_id: str
    principal_id: str
    approval_id: str
    target_ref_hash: str
    target_label: str
    kind: TargetMemoryKind
    content: str
    source: TargetMemorySource
    reason: str
    confidence: float
    evidence_ref_hash: str | None = None
    approval_ref_hash: str | None = None
    source_reference_hash: str | None = None
    chat_guid_hash: str | None = None


class SparkTargetMemoryScorecard(BaseModel):
    active_count: int
    proposal_count: int
    open_loop_count: int
    preference_count: int
    profile_fact_count: int
    readiness: str


class SparkTargetMemoryReviewResponse(BaseModel):
    principal_id: str
    approval_id: str
    target_ref_hash: str
    target_label: str
    active: list[SparkTargetMemoryItem]
    proposals: list[SparkTargetMemoryProposalModel]
    scorecard: SparkTargetMemoryScorecard


class SparkTargetMemoryProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    approval_id: str = Field(min_length=1, max_length=160)
    kind: TargetMemoryKind
    note: str = Field(min_length=3, max_length=800)
    chat_guid_hash: str = Field(min_length=64, max_length=64)


class SparkTargetMemoryProposeResponse(BaseModel):
    status: str
    proposal: SparkTargetMemoryProposalModel | None = None
    reason: str | None = None


class SparkTargetMemoryApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool = True
    proposal_id: str = Field(min_length=8, max_length=64)
    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    target_ref_hash: str = Field(min_length=64, max_length=64)
    target_label: str = Field(min_length=1, max_length=120)
    kind: TargetMemoryKind
    content: str = Field(min_length=1, max_length=500)
    source: TargetMemorySource = "thread_mark"
    evidence_ref_hash: str | None = Field(default=None, min_length=64, max_length=64)
    importance_score: float = Field(default=0.8, ge=0.0, le=1.0)


class SparkTargetMemoryApproveResponse(BaseModel):
    status: str
    result: dict[str, object]


class SparkTargetMemoryArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    memory_id: str = Field(min_length=8, max_length=64)


class SparkTargetMemoryArchiveResponse(BaseModel):
    status: str
    result: dict[str, object]


class SparkTargetMemoryRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    target_ref_hash: str = Field(min_length=64, max_length=64)
    proposal_id: str = Field(min_length=8, max_length=64)


class SparkTargetMemoryRejectResponse(BaseModel):
    status: str
    result: dict[str, object]


class SparkMemoryRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    note: str = Field(min_length=3, max_length=800)
    dry_run: bool = False
    target_label: str | None = Field(default=None, min_length=1, max_length=120)
    target_ref_hash: str | None = Field(default=None, min_length=64, max_length=64)
    approval_id: str | None = Field(default=None, min_length=1, max_length=160)
    approval_ref_hash: str | None = Field(default=None, min_length=64, max_length=64)
    source_reference_hash: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    chat_guid_hash: str | None = Field(default=None, min_length=64, max_length=64)


class SparkMemoryRoutePlanModel(BaseModel):
    status: str
    destination: str | None = None
    reason: str
    risk: str
    review_lane: str
    confidence: float
    semantic_category: str | None = None
    personality_kind: str | None = None
    target_kind: str | None = None
    graph_label_preview: str | None = None
    required_metadata: list[str] = Field(default_factory=list)
    extraction_tags: list[str] = Field(default_factory=list)
    extracted_entities: list[str] = Field(default_factory=list)
    extracted_phrases: list[str] = Field(default_factory=list)
    extracted_traits: list[str] = Field(default_factory=list)
    extracted_projects: list[str] = Field(default_factory=list)
    extracted_locations: list[str] = Field(default_factory=list)
    temporal_kind: str | None = None
    currentness_policy: str | None = None
    review_reasons: list[str] = Field(default_factory=list)


class SparkMemoryRouteResultModel(BaseModel):
    destination: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class SparkMemoryRouteResponse(BaseModel):
    status: str
    principal_id: str
    plan: SparkMemoryRoutePlanModel
    results: list[SparkMemoryRouteResultModel] = Field(default_factory=list)


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
        rows = await fetch_personality_memory(
            conn,
            principal_id,
            limit=SPARK_PERSONALITY_MEMORY_REVIEW_LIMIT,
        )
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
                1
                for proposal in proposals
                if proposal.source == "spark_feedback" and proposal.kind == "phrase"
            ),
            "feedback_lesson_count": sum(
                1
                for proposal in proposals
                if proposal.source == "spark_feedback" and proposal.kind != "phrase"
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


@router.get("/target-memory", response_model=SparkTargetMemoryReviewResponse)
async def get_spark_target_memory(
    request: Request,
    principal_id: str = "ken",
    approval_id: str | None = None,
    _: str = Depends(require_auth),
) -> SparkTargetMemoryReviewResponse:
    check_scopes(request, "admin")
    if not approval_id:
        raise HTTPException(status_code=422, detail="approval_id_required")
    record = _approved_imessage_record(
        principal_id=principal_id, approval_id=approval_id
    )
    async with rls_connection(request) as conn:
        rows = await fetch_target_memory(
            conn,
            principal_id,
            record.source_reference_hash,
        )
    proposals = list_target_memory_proposals(
        principal_id=principal_id,
        target_ref_hash=record.source_reference_hash,
        existing_rows=rows,
    )
    logger.info(
        "spark_target_memory_reviewed",
        extra={
            "event": "spark_target_memory_reviewed",
            "component": "spark_persona",
            "principal_id": principal_id,
            "approval_ref_hash": record.approval_ref_hash,
            "source_reference_hash": record.source_reference_hash,
            "active_count": len(rows),
            "proposal_count": len(proposals),
            "actor_sub": str(getattr(request.state, "user_id", "unknown")),
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return SparkTargetMemoryReviewResponse(
        principal_id=principal_id,
        approval_id=record.approval_id,
        target_ref_hash=record.source_reference_hash,
        target_label=record.source_reference_label or "Approved iMessage thread",
        active=[_target_item(row) for row in rows],
        proposals=[
            SparkTargetMemoryProposalModel(**asdict(proposal)) for proposal in proposals
        ],
        scorecard=_target_memory_scorecard(rows, proposals),
    )


@router.post("/target-memory/propose", response_model=SparkTargetMemoryProposeResponse)
async def propose_spark_target_memory(
    request: Request,
    payload: SparkTargetMemoryProposeRequest,
    _: str = Depends(require_auth),
) -> SparkTargetMemoryProposeResponse:
    check_scopes(request, "admin")
    record = _approved_imessage_record(
        principal_id=payload.principal_id,
        approval_id=payload.approval_id,
    )
    try:
        proposal = propose_target_memory_from_note(
            principal_id=payload.principal_id,
            approval_id=payload.approval_id,
            target_ref_hash=record.source_reference_hash,
            target_label=record.source_reference_label or "Approved iMessage thread",
            kind=payload.kind,
            note=payload.note,
            approval_ref_hash=record.approval_ref_hash,
            source_reference_hash=record.source_reference_hash,
            chat_guid_hash=payload.chat_guid_hash,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_target_memory_proposal_failed"
        ) from exc

    actor_sub = str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    logger.info(
        "spark_target_memory_proposed",
        extra={
            "event": "spark_target_memory_proposed",
            "component": "spark_persona",
            "principal_id": payload.principal_id,
            "approval_ref_hash": record.approval_ref_hash,
            "source_reference_hash": record.source_reference_hash,
            "kind": payload.kind,
            "proposed": proposal is not None,
            "proposal_id": proposal.proposal_id if proposal else "",
            "actor_sub": actor_sub,
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    if proposal is None:
        return SparkTargetMemoryProposeResponse(
            status="not_proposed",
            reason="invalid_or_sensitive_note",
        )
    return SparkTargetMemoryProposeResponse(
        status="proposed",
        proposal=SparkTargetMemoryProposalModel(**asdict(proposal)),
    )


@router.post("/target-memory/approve", response_model=SparkTargetMemoryApproveResponse)
async def approve_spark_target_memory(
    request: Request,
    payload: SparkTargetMemoryApproveRequest,
    _: str = Depends(require_auth),
) -> SparkTargetMemoryApproveResponse:
    check_scopes(request, "admin")
    if not payload.approved:
        raise HTTPException(
            status_code=400,
            detail="spark_target_memory_approval_required",
        )

    approved_by = str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    async with rls_connection(request) as conn:
        result = await save_target_memory(
            conn,
            principal_id=payload.principal_id,
            target_ref_hash=payload.target_ref_hash,
            target_label=payload.target_label,
            kind=payload.kind,
            content=payload.content,
            source=payload.source,
            evidence_ref_hash=payload.evidence_ref_hash,
            approved_by=approved_by,
            importance_score=payload.importance_score,
        )
    logger.info(
        "spark_target_memory_approved",
        extra={
            "event": "spark_target_memory_approved",
            "component": "spark_persona",
            "principal_id": payload.principal_id,
            "target_ref_hash": payload.target_ref_hash,
            "kind": payload.kind,
            "saved": result.get("saved"),
            "proposal_id": payload.proposal_id,
            "actor_sub": approved_by,
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return SparkTargetMemoryApproveResponse(
        status="saved" if result.get("saved") else "not_saved",
        result=result,
    )


@router.post("/target-memory/archive", response_model=SparkTargetMemoryArchiveResponse)
async def archive_spark_target_memory_route(
    request: Request,
    payload: SparkTargetMemoryArchiveRequest,
    _: str = Depends(require_auth),
) -> SparkTargetMemoryArchiveResponse:
    check_scopes(request, "admin")
    archived_by = str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    try:
        async with rls_connection(request) as conn:
            result = await archive_target_memory(
                conn,
                principal_id=payload.principal_id,
                memory_id=payload.memory_id,
                archived_by=archived_by,
            )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_target_memory_archive_failed"
        ) from exc
    logger.info(
        "spark_target_memory_archived",
        extra={
            "event": "spark_target_memory_archived",
            "component": "spark_persona",
            "principal_id": payload.principal_id,
            "memory_id": payload.memory_id,
            "archived": result.get("archived"),
            "actor_sub": archived_by,
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return SparkTargetMemoryArchiveResponse(
        status="archived" if result.get("archived") else "not_archived",
        result=result,
    )


@router.post("/target-memory/reject", response_model=SparkTargetMemoryRejectResponse)
async def reject_spark_target_memory(
    request: Request,
    payload: SparkTargetMemoryRejectRequest,
    _: str = Depends(require_auth),
) -> SparkTargetMemoryRejectResponse:
    check_scopes(request, "admin")
    rejected_by = str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    try:
        result = reject_target_memory_proposal(
            principal_id=payload.principal_id,
            target_ref_hash=payload.target_ref_hash,
            proposal_id=payload.proposal_id,
            rejected_by=rejected_by,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_target_memory_reject_failed"
        ) from exc
    logger.info(
        "spark_target_memory_proposal_rejected",
        extra={
            "event": "spark_target_memory_proposal_rejected",
            "component": "spark_persona",
            "principal_id": payload.principal_id,
            "target_ref_hash": payload.target_ref_hash,
            "proposal_id": payload.proposal_id,
            "rejected": result.get("rejected"),
            "actor_sub": rejected_by,
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return SparkTargetMemoryRejectResponse(
        status="rejected" if result.get("rejected") else "not_rejected",
        result=result,
    )


@router.post("/memory/route", response_model=SparkMemoryRouteResponse)
async def route_spark_memory_learning(
    request: Request,
    payload: SparkMemoryRouteRequest,
    _: str = Depends(require_auth),
) -> SparkMemoryRouteResponse:
    check_scopes(request, "admin")
    target_context = _target_context_from_request(payload)
    plan = plan_spark_memory_route(
        note=payload.note,
        principal_id=payload.principal_id,
        target_label=target_context.get("target_label"),
        has_target_context=bool(target_context),
    )
    result_models: list[SparkMemoryRouteResultModel] = []
    status = "planned" if payload.dry_run else "routed"
    if plan.status == "rejected":
        status = "not_routed"
    elif not payload.dry_run:
        result_models.append(
            await _apply_spark_memory_route(
                request=request,
                payload=payload,
                plan=plan,
                target_context=target_context,
            )
        )
        if result_models[0].status in {"not_routed", "not_proposed", "not_queued"}:
            status = "not_routed"

    logger.info(
        "spark_memory_learning_routed",
        extra={
            "event": "spark_memory_learning_routed",
            "component": "spark_persona",
            "principal_id": payload.principal_id,
            "destination": plan.destination or "",
            "status": status,
            "review_lane": plan.review_lane,
            "note_length": len(payload.note),
            "dry_run": payload.dry_run,
            "actor_sub": str(getattr(request.state, "user_id", "unknown")),
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return SparkMemoryRouteResponse(
        status=status,
        principal_id=payload.principal_id,
        plan=_route_plan_model(plan),
        results=result_models,
    )


async def _apply_spark_memory_route(
    *,
    request: Request,
    payload: SparkMemoryRouteRequest,
    plan: SparkMemoryRoutePlan,
    target_context: dict[str, str],
) -> SparkMemoryRouteResultModel:
    if plan.destination == "spark_personality":
        proposal = propose_personality_memory_from_note(
            principal_id=payload.principal_id,
            note=plan.note,
        )
        return SparkMemoryRouteResultModel(
            destination="spark_personality",
            status="proposed" if proposal else "not_proposed",
            result=(
                {"proposal": asdict(proposal)}
                if proposal
                else {"reason": "invalid_or_sensitive_note"}
            ),
            reason=plan.reason,
        )
    if plan.destination == "spark_target":
        return _route_target_memory(
            payload=payload, plan=plan, target_context=target_context
        )
    if plan.destination == "temporal_graph":
        result = await _route_graph_memory(request=request, payload=payload, plan=plan)
        return SparkMemoryRouteResultModel(
            destination="temporal_graph",
            status=str(result.get("status") or "not_queued"),
            result=result,
            reason=plan.reason,
        )
    if plan.destination == "semantic":
        result = await _route_semantic_memory(
            request=request, payload=payload, plan=plan
        )
        return SparkMemoryRouteResultModel(
            destination="semantic",
            status="saved" if result.get("saved") else "not_saved",
            result=result,
            reason=plan.reason,
        )
    return SparkMemoryRouteResultModel(
        destination="unknown",
        status="not_routed",
        result={"reason": "no_destination"},
        reason=plan.reason,
    )


def _route_target_memory(
    *,
    payload: SparkMemoryRouteRequest,
    plan: SparkMemoryRoutePlan,
    target_context: dict[str, str],
) -> SparkMemoryRouteResultModel:
    missing = [key for key in plan.required_metadata if not target_context.get(key)]
    if missing:
        return SparkMemoryRouteResultModel(
            destination="spark_target",
            status="not_routed",
            result={"reason": "target_context_required", "missing": missing},
            reason=plan.reason,
        )
    proposal = propose_target_memory_from_note(
        principal_id=payload.principal_id,
        approval_id=target_context["approval_id"],
        target_ref_hash=target_context["target_ref_hash"],
        target_label=target_context["target_label"],
        kind=plan.target_kind or "profile_fact",  # type: ignore[arg-type]
        note=plan.note,
        approval_ref_hash=target_context["approval_ref_hash"],
        source_reference_hash=target_context["source_reference_hash"],
        chat_guid_hash=target_context["chat_guid_hash"],
    )
    return SparkMemoryRouteResultModel(
        destination="spark_target",
        status="proposed" if proposal else "not_proposed",
        result=(
            {"proposal": asdict(proposal)}
            if proposal
            else {"reason": "invalid_or_sensitive_note"}
        ),
        reason=plan.reason,
    )


async def _route_semantic_memory(
    *,
    request: Request,
    payload: SparkMemoryRouteRequest,
    plan: SparkMemoryRoutePlan,
) -> dict[str, object]:
    user_id = _principal_uuid(payload.principal_id)
    provenance = {
        "source_surface": "spark_memory_router",
        "source_route": "/v1/spark/persona/memory/route",
        "source_action": "spark_learning_route",
        "actor_type": str(getattr(request.state, "actor_type", "user") or "user"),
        "actor_role": str(getattr(request.state, "role", "admin") or "admin"),
        "review_lane": plan.review_lane,
        "route_reason": plan.reason,
        "contains_raw_spark_body": False,
        "source_note_hash": _sha256(plan.note),
    }
    async with rls_connection(request) as conn:
        return await MemoryService().save_semantic(
            conn=conn,
            user_id=user_id,
            fact=plan.note,
            category=plan.semantic_category or "project",
            provenance=provenance,
            review_status=(
                "pending_review"
                if plan.review_lane == "semantic_high_visibility"
                else None
            ),
            review_reason=(
                "spark_router_high_visibility"
                if plan.review_lane == "semantic_high_visibility"
                else None
            ),
        )


async def _route_graph_memory(
    *,
    request: Request,
    payload: SparkMemoryRouteRequest,
    plan: SparkMemoryRoutePlan,
) -> dict[str, Any]:
    actor = str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    async with rls_connection(request) as conn:
        raw = await conn.fetchval(
            """
            SELECT public.propose_memory_graph_write(
                $1::uuid,
                'create_node',
                'node',
                $2::jsonb,
                'spark_memory_router',
                $3,
                $4
            )
            """,
            str(_principal_uuid(payload.principal_id)),
            json.dumps(plan.graph_payload or {}, sort_keys=True),
            actor,
            plan.reason,
        )
    return _json_result(raw)


def _target_context_from_request(payload: SparkMemoryRouteRequest) -> dict[str, str]:
    context: dict[str, str] = {}
    if payload.approval_id:
        try:
            record = _approved_imessage_record(
                principal_id=payload.principal_id,
                approval_id=payload.approval_id,
            )
        except HTTPException:
            record = None
        if record is not None:
            context.update(
                {
                    "approval_id": record.approval_id,
                    "target_ref_hash": record.source_reference_hash,
                    "target_label": record.source_reference_label
                    or "Approved iMessage thread",
                    "approval_ref_hash": record.approval_ref_hash,
                    "source_reference_hash": record.source_reference_hash,
                }
            )
    if payload.approval_id:
        context["approval_id"] = payload.approval_id
    if payload.target_ref_hash:
        context["target_ref_hash"] = payload.target_ref_hash
    if payload.target_label:
        context["target_label"] = payload.target_label
    if payload.approval_ref_hash:
        context["approval_ref_hash"] = payload.approval_ref_hash
    if payload.source_reference_hash:
        context["source_reference_hash"] = payload.source_reference_hash
    elif payload.target_ref_hash:
        context.setdefault("source_reference_hash", payload.target_ref_hash)
    if payload.chat_guid_hash:
        context["chat_guid_hash"] = payload.chat_guid_hash
    return context


def _route_plan_model(plan: SparkMemoryRoutePlan) -> SparkMemoryRoutePlanModel:
    graph_label = None
    if plan.graph_payload:
        graph_label = str(plan.graph_payload.get("label_preview") or "")
    return SparkMemoryRoutePlanModel(
        status=plan.status,
        destination=plan.destination,
        reason=plan.reason,
        risk=plan.risk,
        review_lane=plan.review_lane,
        confidence=plan.confidence,
        semantic_category=plan.semantic_category,
        personality_kind=plan.personality_kind,
        target_kind=plan.target_kind,
        graph_label_preview=graph_label or None,
        required_metadata=list(plan.required_metadata),
        extraction_tags=list(plan.extraction_tags),
        extracted_entities=list(plan.extracted_entities),
        extracted_phrases=list(plan.extracted_phrases),
        extracted_traits=list(plan.extracted_traits),
        extracted_projects=list(plan.extracted_projects),
        extracted_locations=list(plan.extracted_locations),
        temporal_kind=plan.temporal_kind,
        currentness_policy=plan.currentness_policy,
        review_reasons=list(plan.review_reasons),
    )


def _principal_uuid(principal_id: str) -> UUID:
    try:
        return UUID(str(principal_id))
    except ValueError:
        return uuid5(NAMESPACE_DNS, str(principal_id))


def _json_result(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {"value": loaded}
    return {"value": value}


def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _target_item(row: dict[str, object]) -> SparkTargetMemoryItem:
    return SparkTargetMemoryItem(
        id=str(row["id"]),
        principal_id=str(row["principal_id"]),
        target_ref_hash=str(row["target_ref_hash"]),
        target_label=str(row["target_label"]),
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


def _target_memory_scorecard(
    rows: list[dict[str, object]],
    proposals: tuple[SparkTargetMemoryProposal, ...],
) -> SparkTargetMemoryScorecard:
    active_count = len(rows)
    proposal_count = len(proposals)
    open_loop_count = sum(1 for row in rows if str(row.get("kind")) == "open_loop")
    preference_count = sum(1 for row in rows if str(row.get("kind")) == "preference")
    profile_fact_count = sum(
        1 for row in rows if str(row.get("kind")) == "profile_fact"
    )
    if open_loop_count >= 1 and active_count >= 2:
        readiness = "strong"
    elif active_count or proposal_count:
        readiness = "needs_review"
    else:
        readiness = "thin"
    return SparkTargetMemoryScorecard(
        active_count=active_count,
        proposal_count=proposal_count,
        open_loop_count=open_loop_count,
        preference_count=preference_count,
        profile_fact_count=profile_fact_count,
        readiness=readiness,
    )


def _approved_imessage_record(
    *,
    principal_id: str,
    approval_id: str,
) -> SparkApprovedSourceRecord:
    try:
        records = load_approved_voice_sources(principal_id=principal_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="spark_target_memory_source_unavailable",
        ) from exc
    for record in records:
        if (
            record.source == "imessage"
            and record.decision_approved
            and record.approval_id == approval_id
        ):
            return record
    raise HTTPException(status_code=404, detail="spark_target_memory_target_not_found")


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
        and getattr(proposal, "kind", None) == "phrase"
    )
    feedback_lesson_count = sum(
        1
        for proposal in proposals
        if getattr(proposal, "source", None) == "spark_feedback"
        and getattr(proposal, "kind", None) != "phrase"
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
        feedback_lesson_count=feedback_lesson_count,
        kinds_present=kinds_present,
        missing_core_kinds=missing,
        readiness=readiness,
    )


def _iso(value: object) -> str | None:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value) if value else None
