"""Spark iMessage metadata routes.

These endpoints are deliberately metadata-only. They prove the BlueBubbles
bridge is reachable without exposing contacts or message bodies.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.bluebubbles_client import (
    BlueBubblesClientError,
    BlueBubblesConfigError,
    BlueBubblesCounts,
    BlueBubblesHealth,
    BlueBubblesPolicyError,
    BlueBubblesReadOnlyClient,
    BlueBubblesRecentChatMetadata,
)
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/spark/imessage", tags=["spark-imessage"])
logger = get_logger("alpha_brain")
SPARK_READ_SCOPE = "imessage.read"


class SparkIMessageHealthOut(BaseModel):
    status: str
    computer_id: str | None
    os_version: str | None
    server_version: str | None
    private_api: bool
    proxy_service: str | None
    helper_connected: bool
    detected_icloud: bool
    detected_imessage: bool
    mode: str = "read_only"
    body_access: bool = False


class SparkIMessageCountsOut(BaseModel):
    total_chats: int
    imessage_chats: int
    sms_chats: int
    rcs_chats: int
    sent_messages: int
    body_access: bool = False


class SparkIMessageRecentChatMetadataOut(BaseModel):
    status: int
    message: str
    count: int
    total: int
    offset: int
    limit: int
    data_count: int
    body_access: bool = False


def _check_read_scope(request: Request) -> None:
    check_scopes(request, SPARK_READ_SCOPE)


def _client() -> BlueBubblesReadOnlyClient:
    return BlueBubblesReadOnlyClient()


def _route_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (BlueBubblesConfigError, BlueBubblesPolicyError)):
        return HTTPException(status_code=503, detail="spark_imessage_unavailable")
    if isinstance(exc, BlueBubblesClientError):
        return HTTPException(status_code=502, detail="bluebubbles_read_failed")
    return HTTPException(status_code=500, detail="spark_imessage_error")


def _safe_actor_fields(request: Request) -> dict[str, object]:
    state = request.state
    return {
        "actor_sub": str(getattr(state, "user_id", "unknown")),
        "actor_type": str(getattr(state, "actor_type", "unknown")),
        "actor_iss": str(getattr(state, "iss", "unknown")),
        "scopes_used": [SPARK_READ_SCOPE],
        "risk_tier": "T2",
    }


def _log_success(
    request: Request,
    *,
    action: str,
    fields: dict[str, object] | None = None,
) -> None:
    event = f"spark_imessage_{action}_checked"
    extra = {
        "event": event,
        "component": "spark_imessage",
        "action": action,
        "body_access": False,
        **_safe_actor_fields(request),
    }
    if fields:
        extra.update(fields)
    logger.info(event, extra=extra)


def _log_failure(
    request: Request,
    *,
    action: str,
    exc: Exception,
    status_code: int,
) -> None:
    event = f"spark_imessage_{action}_failed"
    extra = {
        "event": event,
        "component": "spark_imessage",
        "action": action,
        "body_access": False,
        "error_class": exc.__class__.__name__,
        "status_code": status_code,
        **_safe_actor_fields(request),
    }
    if status_code >= 500 and not isinstance(
        exc, (BlueBubblesClientError, BlueBubblesConfigError, BlueBubblesPolicyError)
    ):
        logger.error(event, extra=extra)
        return
    logger.warning(event, extra=extra)


@router.get("/health", response_model=SparkIMessageHealthOut)
async def spark_imessage_health(
    request: Request,
    _: str = Depends(require_auth),
) -> SparkIMessageHealthOut:
    _check_read_scope(request)
    try:
        health = await _client().health()
    except Exception as exc:
        route_error = _route_error(exc)
        _log_failure(
            request,
            action="health",
            exc=exc,
            status_code=route_error.status_code,
        )
        raise route_error from exc
    response = _health_out(health)
    _log_success(
        request,
        action="health",
        fields={
            "bluebubbles_status": response.status,
            "private_api": response.private_api,
            "proxy_service": response.proxy_service,
            "helper_connected": response.helper_connected,
            "detected_icloud": response.detected_icloud,
            "detected_imessage": response.detected_imessage,
            "server_version_present": bool(response.server_version),
        },
    )
    return response


@router.get("/counts", response_model=SparkIMessageCountsOut)
async def spark_imessage_counts(
    request: Request,
    _: str = Depends(require_auth),
) -> SparkIMessageCountsOut:
    _check_read_scope(request)
    try:
        counts = await _client().counts()
    except Exception as exc:
        route_error = _route_error(exc)
        _log_failure(
            request,
            action="counts",
            exc=exc,
            status_code=route_error.status_code,
        )
        raise route_error from exc
    response = _counts_out(counts)
    _log_success(
        request,
        action="counts",
        fields={
            "total_chats": response.total_chats,
            "imessage_chats": response.imessage_chats,
            "sms_chats": response.sms_chats,
            "rcs_chats": response.rcs_chats,
            "sent_messages": response.sent_messages,
        },
    )
    return response


@router.get("/recent-chats/metadata", response_model=SparkIMessageRecentChatMetadataOut)
async def spark_imessage_recent_chat_metadata(
    request: Request,
    _: str = Depends(require_auth),
    limit: int = Query(default=5, ge=1, le=25),
    offset: int = Query(default=0, ge=0),
) -> SparkIMessageRecentChatMetadataOut:
    _check_read_scope(request)
    try:
        metadata = await _client().recent_chat_metadata(limit=limit, offset=offset)
    except Exception as exc:
        route_error = _route_error(exc)
        _log_failure(
            request,
            action="recent_chat_metadata",
            exc=exc,
            status_code=route_error.status_code,
        )
        raise route_error from exc
    response = _metadata_out(metadata)
    _log_success(
        request,
        action="recent_chat_metadata",
        fields={
            "limit": response.limit,
            "offset": response.offset,
            "result_count": response.count,
            "total": response.total,
            "data_count": response.data_count,
        },
    )
    return response


def _health_out(health: BlueBubblesHealth) -> SparkIMessageHealthOut:
    return SparkIMessageHealthOut(**asdict(health))


def _counts_out(counts: BlueBubblesCounts) -> SparkIMessageCountsOut:
    return SparkIMessageCountsOut(**asdict(counts))


def _metadata_out(
    metadata: BlueBubblesRecentChatMetadata,
) -> SparkIMessageRecentChatMetadataOut:
    return SparkIMessageRecentChatMetadataOut(**asdict(metadata))
