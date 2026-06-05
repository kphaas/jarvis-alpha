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

router = APIRouter(prefix="/v1/spark/imessage", tags=["spark-imessage"])


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
    check_scopes(request, "imessage.read")


def _client() -> BlueBubblesReadOnlyClient:
    return BlueBubblesReadOnlyClient()


def _route_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (BlueBubblesConfigError, BlueBubblesPolicyError)):
        return HTTPException(status_code=503, detail="spark_imessage_unavailable")
    if isinstance(exc, BlueBubblesClientError):
        return HTTPException(status_code=502, detail="bluebubbles_read_failed")
    return HTTPException(status_code=500, detail="spark_imessage_error")


@router.get("/health", response_model=SparkIMessageHealthOut)
async def spark_imessage_health(
    request: Request,
    _: str = Depends(require_auth),
) -> SparkIMessageHealthOut:
    _check_read_scope(request)
    try:
        health = await _client().health()
    except Exception as exc:
        raise _route_error(exc) from exc
    return _health_out(health)


@router.get("/counts", response_model=SparkIMessageCountsOut)
async def spark_imessage_counts(
    request: Request,
    _: str = Depends(require_auth),
) -> SparkIMessageCountsOut:
    _check_read_scope(request)
    try:
        counts = await _client().counts()
    except Exception as exc:
        raise _route_error(exc) from exc
    return _counts_out(counts)


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
        raise _route_error(exc) from exc
    return _metadata_out(metadata)


def _health_out(health: BlueBubblesHealth) -> SparkIMessageHealthOut:
    return SparkIMessageHealthOut(**asdict(health))


def _counts_out(counts: BlueBubblesCounts) -> SparkIMessageCountsOut:
    return SparkIMessageCountsOut(**asdict(counts))


def _metadata_out(
    metadata: BlueBubblesRecentChatMetadata,
) -> SparkIMessageRecentChatMetadataOut:
    return SparkIMessageRecentChatMetadataOut(**asdict(metadata))
