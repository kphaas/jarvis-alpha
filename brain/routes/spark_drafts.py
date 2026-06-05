"""Spark draft proposal routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

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
    create_imessage_draft_proposal,
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
    try:
        proposal = await create_imessage_draft_proposal(
            principal_id=payload.principal_id,
            approval_id=payload.approval_id,
            reply_goal=payload.reply_goal,
            max_context_messages=payload.max_context_messages,
        )
    except Exception as exc:
        route_error = _route_error(exc)
        _log_failure(request, exc=exc, status_code=route_error.status_code)
        raise route_error from exc
    _log_success(request, proposal)
    return SparkIMessageDraftOut(**proposal.to_payload())
