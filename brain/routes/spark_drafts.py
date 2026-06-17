"""Spark draft proposal routes."""

from __future__ import annotations

from uuid import UUID, uuid4

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
    SparkIMessageTargetPreview,
    apply_draft_text_override,
    create_imessage_draft_proposal,
    load_imessage_target_preview,
    personality_memory_prompt_items,
)
from brain.services.spark_draft_approvals import enqueue_spark_draft_approval
from brain.services.spark_outbox import (
    SparkOutboxConfigError,
    SparkOutboxCreateResult,
    SparkOutboxStoreError,
    create_spark_outbox_item,
    list_spark_outbox_items,
    load_spark_outbox_crypto,
)
from brain.services.spark_outbox_send import (
    PreparedSparkOutboxSend,
    SparkOutboxSendError,
    SparkOutboxSendResult,
    execute_prepared_spark_imessage_send,
    prepare_approved_spark_imessage_outbox_send,
    record_prepared_spark_imessage_send_failure,
    record_prepared_spark_imessage_send_success,
)
from brain.services.spark_personality_memory import fetch_personality_memory
from brain.services.spark_persona_guardrails import is_core_family_target_label
from brain.services.spark_target_memory import (
    fetch_target_memory,
    target_memory_prompt_items,
)
from brain.services.spark_voice_feedback import (
    SparkDraftEditFeedbackResult,
    SparkDraftQualityFeedbackLabel,
    SparkDraftQualityFeedbackResult,
    record_spark_draft_edit_feedback,
    record_spark_draft_quality_feedback,
)
from brain.services.spark_voice_ingest import (
    SparkApprovedSourceRecord,
    SparkVoiceIngestError,
    load_approved_voice_sources,
)
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/spark/drafts", tags=["spark-drafts"])
logger = get_logger("alpha_brain")
SPARK_DRAFT_SCOPE = "spark.draft"
SPARK_READ_SCOPE = "imessage.read"
SPARK_SEND_SCOPE = "imessage.send"


class SparkIMessageDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    approval_id: str | None = Field(default=None, min_length=1, max_length=160)
    reply_goal: str | None = Field(default=None, max_length=1000)
    max_context_messages: int = Field(default=20, ge=1, le=50)
    style_adjustments: list[str] = Field(default_factory=list, max_length=3)
    include_context_preview: bool = False
    context_preview_limit: int = Field(default=10, ge=1, le=10)
    include_memory_preview: bool = False


class SparkIMessageDraftApprovalRequest(SparkIMessageDraftRequest):
    draft_text_override: str | None = Field(default=None, max_length=4000)


class SparkIMessageDraftTargetOut(BaseModel):
    approval_id: str
    label: str
    channel: str
    thread_kind: str
    relationship_marked: bool
    relationship_approved: bool
    parent_minor_context_approved: bool
    legal_marked: bool


class SparkIMessageDraftTargetsOut(BaseModel):
    principal_id: str
    targets: list[SparkIMessageDraftTargetOut]


class SparkIMessageTargetPreviewOut(BaseModel):
    principal_id: str
    approval_id: str
    label: str
    channel: str
    body_access: bool
    durable_storage_allowed: bool
    context_order: str
    context_messages_read: int
    principal_sent_messages: int
    runtime_context_messages: int
    approval_ref_hash: str
    source_reference_hash: str
    chat_guid_hash: str
    context_preview: list["SparkIMessageDraftContextMessageOut"] = Field(
        default_factory=list
    )
    conversation_summary: "SparkIMessageDraftConversationSummaryOut"
    source_readiness: list["SparkIMessageDraftSourceReadinessOut"] = Field(
        default_factory=list
    )


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
    conversation_summary: "SparkIMessageDraftConversationSummaryOut"
    draft_quality: "SparkIMessageDraftQualityOut"
    source_readiness: list["SparkIMessageDraftSourceReadinessOut"] = Field(
        default_factory=list
    )
    context_preview: list["SparkIMessageDraftContextMessageOut"] = Field(
        default_factory=list
    )
    personality_memory_preview: list["SparkIMessageDraftMemoryDebugOut"] = Field(
        default_factory=list
    )
    target_memory_preview: list["SparkIMessageDraftMemoryDebugOut"] = Field(
        default_factory=list
    )


class SparkIMessageDraftContextMessageOut(BaseModel):
    index: int
    speaker: str
    is_from_me: bool
    message_ref_hash: str
    body_text: str


class SparkIMessageDraftConversationSummaryOut(BaseModel):
    channel: str
    voice_principal_label: str
    reply_target_label: str
    reply_target_confidence: str
    context_order: str
    last_message_speaker: str | None = None
    last_message_preview: str | None = None
    last_message_ref_hash: str | None = None


class SparkIMessageDraftQualityCheckOut(BaseModel):
    key: str
    label: str
    passed: bool
    detail: str


class SparkIMessageDraftQualityOut(BaseModel):
    score: int
    verdict: str
    checks: list[SparkIMessageDraftQualityCheckOut]


class SparkIMessageDraftSourceReadinessOut(BaseModel):
    source: str
    channel: str
    status: str
    detail: str


class SparkIMessageDraftMemoryDebugOut(BaseModel):
    kind: str
    content: str
    source: str
    evidence_ref_hash: str | None = None
    reason: str | None = None


class SparkIMessageDraftApprovalOut(SparkIMessageDraftOut):
    queue_id: str
    approval_status: str
    outbox_id: str | None = None
    outbox_status: str | None = None
    outbox_text_hash: str | None = None
    outbox_recorded: bool = False
    voice_feedback_recorded: bool = False
    voice_feedback_ref_hash: str | None = None
    candidate_key_phrases: list[str] = Field(default_factory=list)
    calibration_lessons: list[str] = Field(default_factory=list)


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


class SparkIMessageApprovedSendOut(BaseModel):
    outbox_id: str
    outbox_status: str
    approval_queue_id: str
    approval_status: str
    message_ref_hash: str | None = None
    send_attempt_count: int


class SparkIMessageOutboxItemOut(BaseModel):
    outbox_id: str
    channel: str
    principal_id: str
    target_label: str
    approval_queue_id: str
    draft_text_hash: str
    status: str
    send_attempt_count: int
    created_at: str
    updated_at: str
    sent_at: str | None = None


class SparkIMessageOutboxListOut(BaseModel):
    principal_id: str
    items: list[SparkIMessageOutboxItemOut] = Field(default_factory=list)


def _check_draft_scopes(request: Request) -> None:
    check_scopes(request, SPARK_DRAFT_SCOPE)
    check_scopes(request, SPARK_READ_SCOPE)


def _check_send_scopes(request: Request) -> None:
    check_scopes(request, SPARK_DRAFT_SCOPE)
    check_scopes(request, SPARK_SEND_SCOPE)


def _safe_actor_fields(
    request: Request,
    *,
    scopes_used: list[str] | None = None,
    risk_tier: str = "T2",
) -> dict[str, object]:
    state = request.state
    return {
        "actor_sub": str(getattr(state, "user_id", "unknown")),
        "actor_type": str(getattr(state, "actor_type", "unknown")),
        "actor_iss": str(getattr(state, "iss", "unknown")),
        "scopes_used": scopes_used or [SPARK_DRAFT_SCOPE, SPARK_READ_SCOPE],
        "risk_tier": risk_tier,
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


def _approved_imessage_record(
    principal_id: str,
    approval_id: str | None,
) -> SparkApprovedSourceRecord | None:
    if not approval_id:
        return None
    records = load_approved_voice_sources(principal_id=principal_id)
    for record in records:
        if (
            record.source == "imessage"
            and record.decision_approved
            and record.approval_id == approval_id
        ):
            return record
    return None


async def _load_target_memory_rows(
    request: Request,
    principal_id: str,
    approval_id: str | None,
) -> list[dict[str, object]]:
    if not approval_id:
        return []
    try:
        record = _approved_imessage_record(principal_id, approval_id)
        if record is None:
            return []
        async with rls_connection(request) as conn:
            return await fetch_target_memory(
                conn,
                principal_id,
                record.source_reference_hash,
            )
    except Exception as exc:
        logger.warning(
            "spark_target_memory_load_failed",
            extra={
                "event": "spark_target_memory_load_failed",
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
    if isinstance(exc, (SparkOutboxConfigError, SparkOutboxStoreError)):
        return HTTPException(
            status_code=503,
            detail="spark_imessage_outbox_unavailable",
        )
    return HTTPException(status_code=500, detail="spark_imessage_draft_error")


def _send_route_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (SparkOutboxSendError, SparkOutboxStoreError)):
        return HTTPException(
            status_code=409,
            detail=str(exc) or "spark_outbox_send_not_ready",
        )
    if isinstance(
        exc,
        (
            SparkOutboxConfigError,
            BlueBubblesConfigError,
            BlueBubblesPolicyError,
        ),
    ):
        return HTTPException(status_code=503, detail="spark_imessage_send_unavailable")
    if isinstance(exc, BlueBubblesClientError):
        return HTTPException(status_code=502, detail="spark_imessage_send_failed")
    return HTTPException(status_code=500, detail="spark_imessage_send_error")


def _log_success(
    request: Request,
    proposal: SparkDraftProposal,
    request_payload: SparkIMessageDraftRequest,
) -> None:
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
            "style_adjustment_count": len(request_payload.style_adjustments),
            "detected_sensitivity": payload["detected_sensitivity"],
            "blocked_sensitivity_count": len(payload["blocked_sensitivity"]),
            **_safe_actor_fields(request),
        },
    )


def _proposal_payload(
    proposal: SparkDraftProposal,
    request_payload: SparkIMessageDraftRequest,
    personality_memory_rows: list[dict[str, object]],
    target_memory_rows: list[dict[str, object]],
) -> dict[str, object]:
    personality_preview: list[dict[str, object]] = []
    target_preview: list[dict[str, object]] = []
    if request_payload.include_memory_preview:
        personality_preview = [
            {
                "kind": item.kind,
                "content": item.content,
                "source": item.source,
                "evidence_ref_hash": item.evidence_ref_hash,
                "reason": None,
            }
            for item in personality_memory_prompt_items(personality_memory_rows)
        ]
        target_preview = [
            {
                "kind": item.kind,
                "content": item.content,
                "source": item.source,
                "evidence_ref_hash": item.evidence_ref_hash,
                "reason": item.reason,
            }
            for item in target_memory_prompt_items(target_memory_rows)
        ]
    return proposal.to_payload(
        include_context_preview=request_payload.include_context_preview,
        context_preview_limit=request_payload.context_preview_limit,
        personality_memory_preview=personality_preview,
        target_memory_preview=target_preview,
    )


def _draft_target(record: SparkApprovedSourceRecord) -> SparkIMessageDraftTargetOut:
    return SparkIMessageDraftTargetOut(
        approval_id=record.approval_id,
        label=record.source_reference_label or "Approved iMessage thread",
        channel="iMessage",
        thread_kind=record.thread_kind,
        relationship_marked=record.relationship_marked,
        relationship_approved=record.relationship_approved,
        parent_minor_context_approved=record.parent_minor_context_approved,
        legal_marked=record.legal_marked,
    )


def _preview_payload(
    preview: SparkIMessageTargetPreview,
    *,
    context_preview_limit: int,
) -> dict[str, object]:
    summary = preview.conversation_summary
    if preview.context.messages:
        last_message = preview.context.messages[0]
        last_message_speaker = "Ken" if last_message.is_from_me else "Other"
        last_message_preview = last_message.body_text[:280]
        last_message_ref_hash = last_message.message_ref_hash
    else:
        last_message_speaker = None
        last_message_preview = None
        last_message_ref_hash = None
    return {
        "principal_id": preview.context.principal_id,
        "approval_id": preview.record.approval_id,
        "label": preview.record.source_reference_label or "Approved iMessage thread",
        "channel": "iMessage",
        "body_access": preview.context.body_access,
        "durable_storage_allowed": preview.context.durable_storage_allowed,
        "context_order": summary.context_order,
        "context_messages_read": len(preview.context.messages),
        "principal_sent_messages": preview.context.principal_sent_messages,
        "runtime_context_messages": preview.context.runtime_context_messages,
        "approval_ref_hash": preview.context.approval_ref_hash,
        "source_reference_hash": preview.context.source_reference_hash,
        "chat_guid_hash": preview.context.chat_guid_hash,
        "conversation_summary": {
            "channel": summary.channel,
            "voice_principal_label": summary.voice_principal_label,
            "reply_target_label": summary.reply_target_label,
            "reply_target_confidence": summary.reply_target_confidence,
            "context_order": summary.context_order,
            "last_message_speaker": last_message_speaker,
            "last_message_preview": last_message_preview,
            "last_message_ref_hash": last_message_ref_hash,
        },
        "source_readiness": [
            {
                "source": item.source,
                "channel": item.channel,
                "status": item.status,
                "detail": item.detail,
            }
            for item in preview.source_readiness
        ],
        "context_preview": [
            {
                "index": index,
                "speaker": "Ken" if message.is_from_me else "Other",
                "is_from_me": message.is_from_me,
                "message_ref_hash": message.message_ref_hash,
                "body_text": message.body_text[:900],
            }
            for index, message in enumerate(
                preview.context.messages[:context_preview_limit],
                start=1,
            )
        ],
    }


def _log_approval_success(
    request: Request,
    proposal: SparkDraftProposal,
    *,
    queue_id: str,
    feedback: SparkDraftEditFeedbackResult,
    outbox: SparkOutboxCreateResult | None,
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
            "outbox_recorded": bool(outbox and outbox.outbox_id),
            "outbox_status": outbox.status if outbox else "unavailable",
            "outbox_id": outbox.outbox_id if outbox and outbox.outbox_id else "",
            "outbox_text_hash": outbox.draft_text_hash if outbox else "",
            "voice_feedback_recorded": feedback.recorded,
            "voice_feedback_ref_hash": feedback.feedback_ref_hash or "",
            "candidate_key_phrase_count": len(feedback.candidate_key_phrases),
            "calibration_lesson_count": len(feedback.calibration_lessons),
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


def _log_outbox_failure(
    request: Request,
    proposal: SparkDraftProposal,
    *,
    exc: Exception,
    reason: str,
) -> None:
    event = "spark_outbox_record_failed"
    payload = proposal.to_payload()
    logger.warning(
        event,
        extra={
            "event": event,
            "component": "spark_drafts",
            "action": "imessage_draft_outbox",
            "body_access": False,
            "reason": reason,
            "error_class": exc.__class__.__name__,
            "approval_ref_hash": payload["approval_ref_hash"],
            "source_reference_hash": payload["source_reference_hash"],
            "chat_guid_hash": payload["chat_guid_hash"],
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


def _log_send_success(
    request: Request,
    *,
    result: SparkOutboxSendResult,
) -> None:
    event = "spark_imessage_approved_send_executed"
    logger.info(
        event,
        extra={
            "event": event,
            "component": "spark_drafts",
            "action": "imessage_approved_send",
            "body_access": False,
            "outbox_id": result.outbox_id,
            "outbox_status": result.outbox_status,
            "approval_queue_id": result.approval_queue_id,
            "approval_status": result.approval_status,
            "message_ref_hash": result.message_ref_hash or "",
            "send_attempt_count": result.send_attempt_count,
            **_safe_actor_fields(
                request,
                scopes_used=[SPARK_DRAFT_SCOPE, SPARK_SEND_SCOPE],
                risk_tier="T4",
            ),
        },
    )


def _log_send_failure(
    request: Request,
    *,
    outbox_id: UUID,
    exc: Exception,
    status_code: int,
) -> None:
    event = "spark_imessage_approved_send_failed"
    logger.warning(
        event,
        extra={
            "event": event,
            "component": "spark_drafts",
            "action": "imessage_approved_send",
            "body_access": False,
            "outbox_id": str(outbox_id),
            "error_class": exc.__class__.__name__,
            "status_code": status_code,
            **_safe_actor_fields(
                request,
                scopes_used=[SPARK_DRAFT_SCOPE, SPARK_SEND_SCOPE],
                risk_tier="T4",
            ),
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


@router.get("/imessage/targets", response_model=SparkIMessageDraftTargetsOut)
async def spark_imessage_draft_targets(
    request: Request,
    principal_id: str = "ken",
    _: str = Depends(require_auth),
) -> SparkIMessageDraftTargetsOut:
    _check_draft_scopes(request)
    try:
        records = load_approved_voice_sources(principal_id=principal_id)
    except Exception as exc:
        route_error = _route_error(exc)
        _log_failure(request, exc=exc, status_code=route_error.status_code)
        raise route_error from exc

    targets = [
        _draft_target(record)
        for record in records
        if record.source == "imessage"
        and record.decision_approved
        and is_core_family_target_label(record.source_reference_label)
    ]
    logger.info(
        "spark_imessage_draft_targets_listed",
        extra={
            "event": "spark_imessage_draft_targets_listed",
            "component": "spark_drafts",
            "action": "imessage_draft_targets",
            "body_access": False,
            "principal_id": principal_id,
            "target_count": len(targets),
            **_safe_actor_fields(request),
        },
    )
    return SparkIMessageDraftTargetsOut(principal_id=principal_id, targets=targets)


@router.get("/imessage/target-preview", response_model=SparkIMessageTargetPreviewOut)
async def spark_imessage_target_preview(
    request: Request,
    principal_id: str = "ken",
    approval_id: str | None = None,
    limit: int = 8,
    _: str = Depends(require_auth),
) -> SparkIMessageTargetPreviewOut:
    _check_draft_scopes(request)
    if not approval_id:
        raise HTTPException(status_code=422, detail="approval_id_required")
    bounded_limit = max(1, min(limit, 8))
    personality_memory_rows = await _load_personality_memory_rows(
        request,
        principal_id,
    )
    try:
        preview = await load_imessage_target_preview(
            principal_id=principal_id,
            approval_id=approval_id,
            max_context_messages=bounded_limit,
            personality_memory_rows=personality_memory_rows,
        )
    except Exception as exc:
        route_error = _route_error(exc)
        _log_failure(request, exc=exc, status_code=route_error.status_code)
        raise route_error from exc
    logger.info(
        "spark_imessage_target_preview_loaded",
        extra={
            "event": "spark_imessage_target_preview_loaded",
            "component": "spark_drafts",
            "action": "imessage_target_preview",
            "body_access": True,
            "principal_id": principal_id,
            "context_messages_read": len(preview.context.messages),
            "principal_sent_messages": preview.context.principal_sent_messages,
            "runtime_context_messages": preview.context.runtime_context_messages,
            "approval_ref_hash": preview.context.approval_ref_hash,
            "source_reference_hash": preview.context.source_reference_hash,
            "chat_guid_hash": preview.context.chat_guid_hash,
            **_safe_actor_fields(request),
        },
    )
    return SparkIMessageTargetPreviewOut(
        **_preview_payload(preview, context_preview_limit=bounded_limit)
    )


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
    target_memory_rows = await _load_target_memory_rows(
        request,
        payload.principal_id,
        payload.approval_id,
    )
    try:
        proposal = await create_imessage_draft_proposal(
            principal_id=payload.principal_id,
            approval_id=payload.approval_id,
            reply_goal=payload.reply_goal,
            max_context_messages=payload.max_context_messages,
            style_adjustments=payload.style_adjustments,
            personality_memory_rows=personality_memory_rows,
            target_memory_rows=target_memory_rows,
        )
    except Exception as exc:
        route_error = _route_error(exc)
        _log_failure(request, exc=exc, status_code=route_error.status_code)
        raise route_error from exc
    _log_success(request, proposal, payload)
    return SparkIMessageDraftOut(
        **_proposal_payload(
            proposal,
            payload,
            personality_memory_rows,
            target_memory_rows,
        )
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
    target_memory_rows = await _load_target_memory_rows(
        request,
        payload.principal_id,
        payload.approval_id,
    )
    try:
        original_proposal = await create_imessage_draft_proposal(
            principal_id=payload.principal_id,
            approval_id=payload.approval_id,
            reply_goal=payload.reply_goal,
            max_context_messages=payload.max_context_messages,
            style_adjustments=payload.style_adjustments,
            personality_memory_rows=personality_memory_rows,
            target_memory_rows=target_memory_rows,
        )
        proposal = apply_draft_text_override(
            original_proposal,
            payload.draft_text_override,
        )
        actor_sub = str(getattr(request.state, "user_id", "unknown"))
        actor_type = str(getattr(request.state, "actor_type", "unknown"))
        try:
            crypto = load_spark_outbox_crypto()
        except SparkOutboxConfigError as outbox_exc:
            _log_outbox_failure(
                request,
                proposal,
                exc=outbox_exc,
                reason="config_missing",
            )
            raise
        outbox: SparkOutboxCreateResult | None = None
        async with rls_connection(request) as conn:
            queue_id = await enqueue_spark_draft_approval(
                conn,
                proposal=proposal,
                actor_sub=actor_sub,
                actor_type=actor_type,
                nonce=uuid4().hex,
            )
            try:
                outbox = await create_spark_outbox_item(
                    conn,
                    proposal=proposal,
                    approval_queue_id=queue_id,
                    actor_sub=actor_sub,
                    actor_type=actor_type,
                    crypto=crypto,
                )
                if not outbox.created or not outbox.outbox_id:
                    raise SparkOutboxStoreError(
                        outbox.reason or "spark_outbox_record_failed"
                    )
            except SparkOutboxConfigError as outbox_exc:
                _log_outbox_failure(
                    request,
                    proposal,
                    exc=outbox_exc,
                    reason="config_missing",
                )
                raise
            except Exception as outbox_exc:
                _log_outbox_failure(
                    request,
                    proposal,
                    exc=outbox_exc,
                    reason="store_failed",
                )
                raise
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
    _log_approval_success(
        request,
        proposal,
        queue_id=str(queue_id),
        feedback=feedback,
        outbox=outbox,
    )
    return SparkIMessageDraftApprovalOut(
        **_proposal_payload(
            proposal,
            payload,
            personality_memory_rows,
            target_memory_rows,
        ),
        queue_id=str(queue_id),
        approval_status="pending",
        outbox_id=outbox.outbox_id if outbox else None,
        outbox_status=outbox.status if outbox else None,
        outbox_text_hash=outbox.draft_text_hash if outbox else None,
        outbox_recorded=bool(outbox and outbox.outbox_id),
        voice_feedback_recorded=feedback.recorded,
        voice_feedback_ref_hash=feedback.feedback_ref_hash,
        candidate_key_phrases=list(feedback.candidate_key_phrases),
        calibration_lessons=list(feedback.calibration_lessons),
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


@router.get("/imessage/outbox", response_model=SparkIMessageOutboxListOut)
async def spark_imessage_outbox_items(
    request: Request,
    principal_id: str = "ken",
    limit: int = 25,
    _: str = Depends(require_auth),
) -> SparkIMessageOutboxListOut:
    _check_draft_scopes(request)
    bounded_limit = max(1, min(limit, 50))
    try:
        async with rls_connection(request) as conn:
            items = await list_spark_outbox_items(
                conn,
                principal_id=principal_id,
                limit=bounded_limit,
            )
    except Exception as exc:
        _log_failure(request, exc=exc, status_code=500)
        raise HTTPException(
            status_code=500,
            detail="spark_imessage_outbox_list_failed",
        ) from exc
    logger.info(
        "spark_imessage_outbox_listed",
        extra={
            "event": "spark_imessage_outbox_listed",
            "component": "spark_drafts",
            "action": "imessage_outbox_list",
            "body_access": False,
            "principal_id": principal_id,
            "item_count": len(items),
            **_safe_actor_fields(request),
        },
    )
    return SparkIMessageOutboxListOut(
        principal_id=principal_id,
        items=[
            SparkIMessageOutboxItemOut(
                outbox_id=item.outbox_id,
                channel=item.channel,
                principal_id=item.principal_id,
                target_label=item.target_label,
                approval_queue_id=item.approval_queue_id,
                draft_text_hash=item.draft_text_hash,
                status=item.status,
                send_attempt_count=item.send_attempt_count,
                created_at=item.created_at.isoformat(),
                updated_at=item.updated_at.isoformat(),
                sent_at=item.sent_at.isoformat() if item.sent_at else None,
            )
            for item in items
        ],
    )


@router.post(
    "/imessage/outbox/{outbox_id}/send",
    response_model=SparkIMessageApprovedSendOut,
)
async def spark_imessage_send_approved_outbox(
    request: Request,
    outbox_id: UUID,
    _: str = Depends(require_auth),
) -> SparkIMessageApprovedSendOut:
    _check_send_scopes(request)
    actor_sub = str(getattr(request.state, "user_id", "unknown"))
    actor_type = str(getattr(request.state, "actor_type", "unknown"))
    try:
        async with rls_connection(request) as conn:
            prepared = await prepare_approved_spark_imessage_outbox_send(
                conn,
                outbox_id=outbox_id,
                actor_sub=actor_sub,
                actor_type=actor_type,
                crypto=load_spark_outbox_crypto(),
            )
    except Exception as exc:
        route_error = _send_route_error(exc)
        _log_send_failure(
            request,
            outbox_id=outbox_id,
            exc=exc,
            status_code=route_error.status_code,
        )
        raise route_error from exc

    try:
        send_result = await execute_prepared_spark_imessage_send(prepared)
    except Exception as exc:
        await _record_send_failure_event(request, prepared=prepared, exc=exc)
        route_error = _send_route_error(exc)
        _log_send_failure(
            request,
            outbox_id=outbox_id,
            exc=exc,
            status_code=route_error.status_code,
        )
        raise route_error from exc

    try:
        async with rls_connection(request) as conn:
            result = await record_prepared_spark_imessage_send_success(
                conn,
                prepared=prepared,
                send_result=send_result,
            )
    except Exception as exc:
        route_error = _send_route_error(exc)
        _log_send_failure(
            request,
            outbox_id=outbox_id,
            exc=exc,
            status_code=route_error.status_code,
        )
        raise route_error from exc

    _log_send_success(request, result=result)
    return SparkIMessageApprovedSendOut(
        outbox_id=result.outbox_id,
        outbox_status=result.outbox_status,
        approval_queue_id=result.approval_queue_id,
        approval_status=result.approval_status,
        message_ref_hash=result.message_ref_hash,
        send_attempt_count=result.send_attempt_count,
    )


async def _record_send_failure_event(
    request: Request,
    *,
    prepared: PreparedSparkOutboxSend,
    exc: Exception,
) -> None:
    try:
        async with rls_connection(request) as conn:
            await record_prepared_spark_imessage_send_failure(
                conn,
                prepared=prepared,
                exc=exc,
            )
    except Exception as record_exc:
        logger.error(
            "spark_imessage_send_failed_event_record_failed",
            extra={
                "event": "spark_imessage_send_failed_event_record_failed",
                "component": "spark_drafts",
                "action": "imessage_approved_send",
                "body_access": False,
                "outbox_id": str(prepared.item.outbox_id),
                "error_class": record_exc.__class__.__name__,
                **_safe_actor_fields(
                    request,
                    scopes_used=[SPARK_DRAFT_SCOPE, SPARK_SEND_SCOPE],
                    risk_tier="T4",
                ),
            },
        )
