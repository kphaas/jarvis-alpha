"""Spark draft proposal routes."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.db.rls import rls_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.bluebubbles_client import (
    BlueBubblesClientError,
    BlueBubblesConfigError,
    BlueBubblesPolicyError,
)
from brain.services.spark_imessage_drafts import (
    SparkDraftConfigError,
    SparkDraftContextError,
    SparkDraftPolicyError,
    SparkDraftProposal,
    apply_draft_text_override,
    create_imessage_draft_proposal,
    personality_memory_prompt_items,
)
from brain.services.spark_draft_approvals import enqueue_spark_draft_approval
from brain.services.spark_personality_memory import fetch_personality_memory
from brain.services.spark_voice_feedback import (
    SparkDraftEditFeedbackResult,
    SparkDraftQualityFeedbackLabel,
    SparkDraftQualityFeedbackResult,
    record_spark_draft_edit_feedback,
    record_spark_draft_quality_feedback,
)
from brain.services.spark_voice_ingest import SparkVoiceIngestError
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/spark/drafts", tags=["spark-drafts"])
logger = get_logger("alpha_brain")
SPARK_DRAFT_SCOPE = "spark.draft"
SPARK_READ_SCOPE = "imessage.read"


class SparkIMessageDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    approval_id: str | None = Field(default=None, min_length=1, max_length=160)
    reply_goal: str | None = Field(default=None, max_length=1000)
    max_context_messages: int = Field(default=20, ge=1, le=50)
    include_context_preview: bool = False
    context_preview_limit: int = Field(default=10, ge=1, le=10)
    include_memory_preview: bool = False


class SparkIMessageDraftApprovalRequest(SparkIMessageDraftRequest):
    draft_text_override: str | None = Field(default=None, max_length=4000)


class SparkIMessageDraftOut(BaseModel):
    draft_version: str
    principal_id: str
    draft_text: str
    can_send: bool
    requires_human_approval: bool
    body_access: bool
    durable_storage_allowed: bool
    context_messages_read: int
    principal_sent_messages: int
    runtime_context_messages: int
    approval_ref_hash: str
    source_reference_hash: str
    chat_guid_hash: str
    warnings: list[str]
    detected_sensitivity: list[str]
    blocked_sensitivity: list[str]
    draft_engine: str
    context_preview: list["SparkIMessageDraftContextMessageOut"] = Field(
        default_factory=list
    )
    personality_memory_preview: list["SparkIMessageDraftMemoryDebugOut"] = Field(
        default_factory=list
    )


class SparkIMessageDraftContextMessageOut(BaseModel):
    index: int
    speaker: str
    is_from_me: bool
    message_ref_hash: str
    body_text: str


class SparkIMessageDraftMemoryDebugOut(BaseModel):
    kind: str
    content: str
    source: str
    evidence_ref_hash: str | None = None


class SparkIMessageDraftApprovalOut(SparkIMessageDraftOut):
    queue_id: str
    approval_status: str
    voice_feedback_recorded: bool = False
    voice_feedback_ref_hash: str | None = None
    candidate_key_phrases: list[str] = Field(default_factory=list)


class SparkIMessageDraftFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    feedback_label: SparkDraftQualityFeedbackLabel
    draft_version: str = Field(min_length=1, max_length=80)
    approval_ref_hash: str = Field(min_length=1, max_length=160)
    source_reference_hash: str = Field(min_length=1, max_length=160)
    chat_guid_hash: str = Field(min_length=1, max_length=160)


class SparkIMessageDraftFeedbackOut(BaseModel):
    status: str
    feedback_recorded: bool
    feedback_ref_hash: str | None = None
    feedback_label: SparkDraftQualityFeedbackLabel | None = None


def _check_draft_scopes(request: Request) -> None:
    check_scopes(request, SPARK_DRAFT_SCOPE)
    check_scopes(request, SPARK_READ_SCOPE)


def _safe_actor_fields(request: Request) -> dict[str, object]:
    state = request.state
    return {
        "actor_sub": str(getattr(state, "user_id", "unknown")),
        "actor_type": str(getattr(state, "actor_type", "unknown")),
        "actor_iss": str(getattr(state, "iss", "unknown")),
        "scopes_used": [SPARK_DRAFT_SCOPE, SPARK_READ_SCOPE],
        "risk_tier": "T2",
    }


async def _load_personality_memory_rows(
    request: Request,
    principal_id: str,
) -> list[dict[str, object]]:
    try:
        async with rls_connection(request) as conn:
            return await fetch_personality_memory(conn, principal_id)
    except Exception as exc:
        logger.warning(
            "spark_personality_memory_load_failed",
            extra={
                "event": "spark_personality_memory_load_failed",
                "component": "spark_drafts",
                "principal_id": principal_id,
                "error_class": exc.__class__.__name__,
                **_safe_actor_fields(request),
            },
        )
        return []


def _route_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SparkDraftPolicyError):
        return HTTPException(
            status_code=403,
            detail="spark_imessage_draft_policy_denied",
        )
    if isinstance(
        exc,
        (
            SparkDraftConfigError,
            SparkVoiceIngestError,
            BlueBubblesConfigError,
            BlueBubblesPolicyError,
        ),
    ):
        return HTTPException(
            status_code=503,
            detail="spark_imessage_approved_thread_unavailable",
        )
    if isinstance(exc, (SparkDraftContextError, BlueBubblesClientError)):
        return HTTPException(
            status_code=502,
            detail="spark_imessage_context_load_failed",
        )
    return HTTPException(status_code=500, detail="spark_imessage_draft_error")


def _log_success(request: Request, proposal: SparkDraftProposal) -> None:
    event = "spark_imessage_draft_proposed"
    payload = proposal.to_payload()
    logger.info(
        event,
        extra={
            "event": event,
            "component": "spark_drafts",
            "action": "imessage_draft",
            "body_access": True,
            "can_send": False,
            "requires_human_approval": True,
            "context_messages_read": payload["context_messages_read"],
            "principal_sent_messages": payload["principal_sent_messages"],
            "runtime_context_messages": payload["runtime_context_messages"],
            "approval_ref_hash": payload["approval_ref_hash"],
            "source_reference_hash": payload["source_reference_hash"],
            "chat_guid_hash": payload["chat_guid_hash"],
            "draft_engine": payload["draft_engine"],
            "detected_sensitivity": payload["detected_sensitivity"],
            "blocked_sensitivity_count": len(payload["blocked_sensitivity"]),
            **_safe_actor_fields(request),
        },
    )


def _proposal_payload(
    proposal: SparkDraftProposal,
    request_payload: SparkIMessageDraftRequest,
    personality_memory_rows: list[dict[str, object]],
) -> dict[str, object]:
    memory_preview: list[dict[str, object]] = []
    if request_payload.include_memory_preview:
        memory_preview = [
            {
                "kind": item.kind,
                "content": item.content,
                "source": item.source,
                "evidence_ref_hash": item.evidence_ref_hash,
            }
            for item in personality_memory_prompt_items(personality_memory_rows)
        ]
    return proposal.to_payload(
        include_context_preview=request_payload.include_context_preview,
        context_preview_limit=request_payload.context_preview_limit,
        personality_memory_preview=memory_preview,
    )


def _log_approval_success(
    request: Request,
    proposal: SparkDraftProposal,
    *,
    queue_id: str,
    feedback: SparkDraftEditFeedbackResult,
) -> None:
    event = "spark_imessage_draft_approval_queued"
    payload = proposal.to_payload()
    logger.info(
        event,
        extra={
            "event": event,
            "component": "spark_drafts",
            "action": "imessage_draft_approval",
            "body_access": True,
            "can_send": False,
            "requires_human_approval": True,
            "queue_id": queue_id,
            "voice_feedback_recorded": feedback.recorded,
            "voice_feedback_ref_hash": feedback.feedback_ref_hash or "",
            "candidate_key_phrase_count": len(feedback.candidate_key_phrases),
            "context_messages_read": payload["context_messages_read"],
            "principal_sent_messages": payload["principal_sent_messages"],
            "runtime_context_messages": payload["runtime_context_messages"],
            "approval_ref_hash": payload["approval_ref_hash"],
            "source_reference_hash": payload["source_reference_hash"],
            "chat_guid_hash": payload["chat_guid_hash"],
            "draft_engine": payload["draft_engine"],
            "detected_sensitivity": payload["detected_sensitivity"],
            "blocked_sensitivity_count": len(payload["blocked_sensitivity"]),
            **_safe_actor_fields(request),
        },
    )


def _log_feedback_failure(
    request: Request,
    proposal: SparkDraftProposal,
    *,
    exc: Exception,
) -> None:
    event = "spark_voice_feedback_record_failed"
    payload = proposal.to_payload()
    logger.warning(
        event,
        extra={
            "event": event,
            "component": "spark_drafts",
            "action": "imessage_draft_feedback",
            "body_access": False,
            "error_class": exc.__class__.__name__,
            "approval_ref_hash": payload["approval_ref_hash"],
            "source_reference_hash": payload["source_reference_hash"],
            "chat_guid_hash": payload["chat_guid_hash"],
            **_safe_actor_fields(request),
        },
    )


def _log_quality_feedback_success(
    request: Request,
    payload: SparkIMessageDraftFeedbackRequest,
    *,
    feedback: SparkDraftQualityFeedbackResult,
) -> None:
    event = "spark_imessage_draft_quality_feedback_recorded"
    logger.info(
        event,
        extra={
            "event": event,
            "component": "spark_drafts",
            "action": "imessage_draft_quality_feedback",
            "body_access": False,
            "principal_id": payload.principal_id,
            "feedback_label": payload.feedback_label,
            "feedback_recorded": feedback.recorded,
            "feedback_ref_hash": feedback.feedback_ref_hash or "",
            "approval_ref_hash": payload.approval_ref_hash,
            "source_reference_hash": payload.source_reference_hash,
            "chat_guid_hash": payload.chat_guid_hash,
            **_safe_actor_fields(request),
        },
    )


def _log_failure(
    request: Request,
    *,
    exc: Exception,
    status_code: int,
) -> None:
    event = "spark_imessage_draft_failed"
    extra = {
        "event": event,
        "component": "spark_drafts",
        "action": "imessage_draft",
        "body_access": False,
        "error_class": exc.__class__.__name__,
        "status_code": status_code,
        **_safe_actor_fields(request),
    }
    if status_code >= 500 and not isinstance(
        exc,
        (
            SparkDraftConfigError,
            SparkDraftContextError,
            SparkDraftPolicyError,
            SparkVoiceIngestError,
            BlueBubblesClientError,
            BlueBubblesConfigError,
            BlueBubblesPolicyError,
        ),
    ):
        logger.error(event, extra=extra)
        return
    logger.warning(event, extra=extra)


@router.post("/imessage", response_model=SparkIMessageDraftOut)
async def spark_imessage_draft(
    request: Request,
    payload: SparkIMessageDraftRequest,
    _: str = Depends(require_auth),
) -> SparkIMessageDraftOut:
    _check_draft_scopes(request)
    personality_memory_rows = await _load_personality_memory_rows(
        request,
        payload.principal_id,
    )
    try:
        proposal = await create_imessage_draft_proposal(
            principal_id=payload.principal_id,
            approval_id=payload.approval_id,
            reply_goal=payload.reply_goal,
            max_context_messages=payload.max_context_messages,
            personality_memory_rows=personality_memory_rows,
        )
    except Exception as exc:
        route_error = _route_error(exc)
        _log_failure(request, exc=exc, status_code=route_error.status_code)
        raise route_error from exc
    _log_success(request, proposal)
    return SparkIMessageDraftOut(
        **_proposal_payload(proposal, payload, personality_memory_rows)
    )


@router.post("/imessage/approval-request", response_model=SparkIMessageDraftApprovalOut)
async def spark_imessage_draft_approval_request(
    request: Request,
    payload: SparkIMessageDraftApprovalRequest,
    _: str = Depends(require_auth),
) -> SparkIMessageDraftApprovalOut:
    _check_draft_scopes(request)
    personality_memory_rows = await _load_personality_memory_rows(
        request,
        payload.principal_id,
    )
    try:
        original_proposal = await create_imessage_draft_proposal(
            principal_id=payload.principal_id,
            approval_id=payload.approval_id,
            reply_goal=payload.reply_goal,
            max_context_messages=payload.max_context_messages,
            personality_memory_rows=personality_memory_rows,
        )
        proposal = apply_draft_text_override(
            original_proposal,
            payload.draft_text_override,
        )
        actor_sub = str(getattr(request.state, "user_id", "unknown"))
        actor_type = str(getattr(request.state, "actor_type", "unknown"))
        async with rls_connection(request) as conn:
            queue_id = await enqueue_spark_draft_approval(
                conn,
                proposal=proposal,
                actor_sub=actor_sub,
                actor_type=actor_type,
                nonce=uuid4().hex,
            )
        try:
            feedback = record_spark_draft_edit_feedback(
                original_proposal=original_proposal,
                edited_proposal=proposal,
            )
        except Exception as feedback_exc:
            _log_feedback_failure(request, proposal, exc=feedback_exc)
            feedback = SparkDraftEditFeedbackResult(
                recorded=False,
                feedback_ref_hash=None,
            )
    except Exception as exc:
        route_error = _route_error(exc)
        _log_failure(request, exc=exc, status_code=route_error.status_code)
        raise route_error from exc
    _log_approval_success(request, proposal, queue_id=str(queue_id), feedback=feedback)
    return SparkIMessageDraftApprovalOut(
        **_proposal_payload(proposal, payload, personality_memory_rows),
        queue_id=str(queue_id),
        approval_status="pending",
        voice_feedback_recorded=feedback.recorded,
        voice_feedback_ref_hash=feedback.feedback_ref_hash,
        candidate_key_phrases=list(feedback.candidate_key_phrases),
    )


@router.post("/imessage/feedback", response_model=SparkIMessageDraftFeedbackOut)
async def spark_imessage_draft_feedback(
    request: Request,
    payload: SparkIMessageDraftFeedbackRequest,
    _: str = Depends(require_auth),
) -> SparkIMessageDraftFeedbackOut:
    _check_draft_scopes(request)
    try:
        feedback = record_spark_draft_quality_feedback(
            principal_id=payload.principal_id,
            feedback_label=payload.feedback_label,
            draft_version=payload.draft_version,
            approval_ref_hash=payload.approval_ref_hash,
            source_reference_hash=payload.source_reference_hash,
            chat_guid_hash=payload.chat_guid_hash,
        )
    except Exception as exc:
        _log_failure(request, exc=exc, status_code=500)
        raise HTTPException(
            status_code=500,
            detail="spark_imessage_draft_feedback_failed",
        ) from exc
    _log_quality_feedback_success(request, payload, feedback=feedback)
    return SparkIMessageDraftFeedbackOut(
        status="recorded" if feedback.recorded else "not_recorded",
        feedback_recorded=feedback.recorded,
        feedback_ref_hash=feedback.feedback_ref_hash,
        feedback_label=feedback.feedback_label,
    )
