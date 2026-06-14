"""Alpha-owned Helm voice input gate.

Helm records short browser audio blobs. Alpha owns auth, upload limits, and
backend selection so the browser does not need Family- or AT-0-service tokens.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from brain.config.secrets import get_secret
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/helm", tags=["helm"])
logger = get_logger("alpha_brain")

MAX_VOICE_AUDIO_BYTES = int(os.getenv("JARVIS_HELM_VOICE_MAX_AUDIO_BYTES", "8388608"))
ALLOWED_AUDIO_TYPES = {
    "audio/aac",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "application/octet-stream",
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _secret_or_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        secret = get_secret(name)
    except Exception:
        return None
    return str(secret).strip() or None


def _voice_transcribe_url() -> str | None:
    value = os.getenv("JARVIS_HELM_VOICE_TRANSCRIBE_URL", "").strip()
    return value or None


def _voice_backend_verify_tls() -> bool:
    return _env_bool("JARVIS_HELM_VOICE_VERIFY_TLS", True)


def _voice_backend_timeout_secs() -> float:
    raw = os.getenv("JARVIS_HELM_VOICE_TIMEOUT_SECS", "15").strip()
    try:
        return max(1.0, min(float(raw), 60.0))
    except ValueError:
        return 15.0


def _voice_backend_field_name() -> str:
    value = os.getenv("JARVIS_HELM_VOICE_BACKEND_FIELD", "audio").strip()
    if not value or not value.replace("_", "").replace("-", "").isalnum():
        return "audio"
    return value


def _voice_backend_authorization(request: Request) -> str:
    secret_name = os.getenv("JARVIS_HELM_VOICE_BACKEND_TOKEN_SECRET", "").strip()
    token = _secret_or_env(secret_name) if secret_name else None
    token = token or _secret_or_env("JARVIS_HELM_VOICE_BACKEND_TOKEN")
    token = token or str(getattr(request.state, "jwt_token", "") or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="voice_auth_token_unavailable")
    return f"Bearer {token}"


def _audio_content_type(file: UploadFile) -> str:
    return (file.content_type or "application/octet-stream").split(";", 1)[0].strip()


async def _read_voice_upload(file: UploadFile) -> tuple[bytes, str, str]:
    content_type = _audio_content_type(file)
    if content_type not in ALLOWED_AUDIO_TYPES:
        logger.warning(
            "helm_voice_transcribe_rejected",
            extra={"reason": "unsupported_audio_type", "content_type": content_type},
        )
        raise HTTPException(status_code=415, detail="unsupported_audio_type")

    data = await file.read(MAX_VOICE_AUDIO_BYTES + 1)
    if not data:
        logger.warning(
            "helm_voice_transcribe_rejected", extra={"reason": "empty_audio"}
        )
        raise HTTPException(status_code=400, detail="audio_file_empty")
    if len(data) > MAX_VOICE_AUDIO_BYTES:
        logger.warning(
            "helm_voice_transcribe_rejected",
            extra={"reason": "audio_too_large", "bytes": len(data)},
        )
        raise HTTPException(status_code=413, detail="audio_file_too_large")

    filename = file.filename or "helm-at0-voice.webm"
    return data, filename, content_type


def _transcript_from_payload(payload: dict[str, Any]) -> str:
    for key in ("text", "transcript", "delta"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def _forward_voice_upload(
    *,
    request: Request,
    data: bytes,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    backend_url = _voice_transcribe_url()
    if not backend_url:
        logger.warning(
            "helm_voice_transcribe_unconfigured",
            extra={"reason": "missing_backend_url"},
        )
        raise HTTPException(status_code=503, detail="voice_transcription_unconfigured")

    field_name = _voice_backend_field_name()
    files = {field_name: (filename, data, content_type)}
    headers = {
        "Accept": "application/json",
        "Authorization": _voice_backend_authorization(request),
    }

    try:
        async with httpx.AsyncClient(
            timeout=_voice_backend_timeout_secs(),
            verify=_voice_backend_verify_tls(),
        ) as client:
            response = await client.post(backend_url, headers=headers, files=files)
    except (OSError, httpx.HTTPError) as exc:
        logger.warning(
            "helm_voice_transcribe_backend_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503, detail="voice_backend_unavailable"
        ) from exc

    if response.status_code in {401, 403}:
        logger.warning(
            "helm_voice_transcribe_backend_rejected",
            extra={"backend_status": response.status_code},
        )
        raise HTTPException(status_code=502, detail="voice_backend_rejected")
    if response.status_code >= 400:
        logger.warning(
            "helm_voice_transcribe_backend_failed",
            extra={"backend_status": response.status_code},
        )
        raise HTTPException(status_code=502, detail="voice_backend_failed")

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("helm_voice_transcribe_invalid_backend_json")
        raise HTTPException(
            status_code=502, detail="voice_backend_invalid_response"
        ) from exc
    if not isinstance(payload, dict):
        logger.warning("helm_voice_transcribe_invalid_backend_payload")
        raise HTTPException(status_code=502, detail="voice_backend_invalid_response")

    text = _transcript_from_payload(payload)
    if not text:
        logger.warning("helm_voice_transcribe_empty_transcript")
        raise HTTPException(status_code=502, detail="voice_backend_empty_transcript")

    logger.info(
        "helm_voice_transcribe_ok",
        extra={"bytes": len(data), "content_type": content_type},
    )
    return {
        "text": text,
        "language": payload.get("language")
        if isinstance(payload.get("language"), str)
        else "en",
        "source": "alpha_helm_voice_gate",
    }


@router.post("/voice/transcribe")
async def helm_voice_transcribe(
    request: Request,
    file: UploadFile = File(...),
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    """Transcribe a short Helm AT-0 voice recording through a configured backend."""

    check_scopes(request, "helm.read", "admin")
    data, filename, content_type = await _read_voice_upload(file)
    return await _forward_voice_upload(
        request=request,
        data=data,
        filename=filename,
        content_type=content_type,
    )
