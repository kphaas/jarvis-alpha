"""Alpha-owned Helm voice gates.

Helm records short browser audio blobs. Alpha owns auth, upload limits, and
backend selection so the browser does not need Family- or AT-0-service tokens.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field

from brain.config.secrets import get_secret
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/helm", tags=["helm"])
logger = get_logger("alpha_brain")

MAX_VOICE_AUDIO_BYTES = int(os.getenv("JARVIS_HELM_VOICE_MAX_AUDIO_BYTES", "8388608"))
FAMILY_TOKEN_REFRESH_SKEW_SECS = 300
ALLOWED_AUDIO_TYPES = {
    "audio/aac",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "application/octet-stream",
}
PRESERVED_TRANSCRIBE_BACKEND_DETAILS = {
    "voice_backend_empty_transcript",
    "voice_backend_unavailable",
}
_family_voice_token_cache: dict[str, Any] = {}


class HelmVoiceSpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1200)
    voice: str | None = Field(default=None, max_length=40)
    speed: float = Field(default=1.0, ge=0.75, le=1.25)


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


def _voice_speak_url() -> str | None:
    value = os.getenv("JARVIS_HELM_VOICE_SPEAK_URL", "").strip()
    return value or None


def _family_api_url() -> str | None:
    value = (
        os.getenv("JARVIS_HELM_VOICE_FAMILY_API_URL", "").strip()
        or os.getenv("JARVIS_FAMILY_API_URL", "").strip()
    )
    return value.rstrip("/") or None


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
    token = token or os.getenv("JARVIS_HELM_VOICE_BACKEND_TOKEN", "").strip()
    token = token or str(getattr(request.state, "jwt_token", "") or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="voice_auth_token_unavailable")
    return f"Bearer {token}"


def _voice_speak_backend_token() -> str | None:
    secret_name = os.getenv("JARVIS_HELM_VOICE_SPEAK_BACKEND_TOKEN_SECRET", "").strip()
    if secret_name:
        return _secret_or_env(secret_name)
    token = os.getenv("JARVIS_HELM_VOICE_SPEAK_BACKEND_TOKEN", "").strip()
    return token or None


def _family_voice_auth_name() -> str:
    return os.getenv("JARVIS_HELM_VOICE_FAMILY_AUTH_NAME", "Ken").strip() or "Ken"


def _family_voice_auth_pin() -> str | None:
    secret_name = os.getenv("JARVIS_HELM_VOICE_FAMILY_PIN_SECRET", "").strip()
    pin = _secret_or_env(secret_name) if secret_name else None
    return (
        pin
        or os.getenv("JARVIS_HELM_VOICE_FAMILY_PIN", "").strip()
        or os.getenv("JARVIS_FAMILY_PIN", "").strip()
        or None
    )


def _clear_family_voice_token_cache() -> None:
    _family_voice_token_cache.clear()


def _cached_family_voice_token() -> str | None:
    token = _family_voice_token_cache.get("token")
    expires_at = _family_voice_token_cache.get("expires_at")
    if not isinstance(token, str) or not isinstance(expires_at, (int, float)):
        return None
    if time.time() >= expires_at - FAMILY_TOKEN_REFRESH_SKEW_SECS:
        _clear_family_voice_token_cache()
        return None
    return token


async def _family_voice_token() -> str:
    cached = _cached_family_voice_token()
    if cached:
        return cached

    family_api_url = _family_api_url()
    pin = _family_voice_auth_pin()
    if not family_api_url or not pin:
        logger.warning(
            "helm_voice_speak_unconfigured",
            extra={"reason": "missing_family_auth"},
        )
        raise HTTPException(status_code=503, detail="voice_synthesis_auth_unconfigured")

    try:
        async with httpx.AsyncClient(
            timeout=_voice_backend_timeout_secs(),
            verify=_voice_backend_verify_tls(),
        ) as client:
            response = await client.post(
                f"{family_api_url}/v1/auth/pin",
                headers={"Accept": "application/json"},
                json={"name": _family_voice_auth_name(), "pin": pin},
            )
    except (OSError, httpx.HTTPError) as exc:
        logger.warning(
            "helm_voice_speak_family_auth_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503, detail="voice_synthesis_auth_unavailable"
        ) from exc

    if response.status_code in {401, 403, 429}:
        logger.warning(
            "helm_voice_speak_family_auth_rejected",
            extra={"backend_status": response.status_code},
        )
        raise HTTPException(status_code=502, detail="voice_synthesis_auth_rejected")
    if response.status_code >= 400:
        logger.warning(
            "helm_voice_speak_family_auth_failed",
            extra={"backend_status": response.status_code},
        )
        raise HTTPException(status_code=502, detail="voice_synthesis_auth_failed")

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("helm_voice_speak_family_auth_invalid_json")
        raise HTTPException(
            status_code=502, detail="voice_synthesis_auth_invalid_response"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("token"), str):
        logger.warning("helm_voice_speak_family_auth_invalid_payload")
        raise HTTPException(
            status_code=502, detail="voice_synthesis_auth_invalid_response"
        )

    token = str(payload["token"]).strip()
    _family_voice_token_cache["token"] = token
    _family_voice_token_cache["expires_at"] = time.time() + 20 * 60
    return token


async def _voice_speak_backend_authorization() -> str:
    token = _voice_speak_backend_token() or await _family_voice_token()
    if not token:
        raise HTTPException(status_code=401, detail="voice_synthesis_token_unavailable")
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


def _backend_error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    return detail if isinstance(detail, str) and detail.strip() else None


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
        backend_detail = _backend_error_detail(response)
        logger.warning(
            "helm_voice_transcribe_backend_failed",
            extra={
                "backend_status": response.status_code,
                "backend_detail": backend_detail,
            },
        )
        if backend_detail in PRESERVED_TRANSCRIBE_BACKEND_DETAILS:
            raise HTTPException(status_code=502, detail=backend_detail)
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


async def _forward_voice_speak(request_body: HelmVoiceSpeakRequest) -> Response:
    backend_url = _voice_speak_url()
    if not backend_url:
        logger.warning(
            "helm_voice_speak_unconfigured",
            extra={"reason": "missing_backend_url"},
        )
        raise HTTPException(status_code=503, detail="voice_synthesis_unconfigured")

    payload: dict[str, Any] = {
        "text": request_body.text,
        "speed": request_body.speed,
    }
    if request_body.voice:
        payload["voice"] = request_body.voice

    headers = {
        "Accept": "audio/wav",
        "Authorization": await _voice_speak_backend_authorization(),
    }

    try:
        async with httpx.AsyncClient(
            timeout=_voice_backend_timeout_secs(),
            verify=_voice_backend_verify_tls(),
        ) as client:
            response = await client.post(backend_url, headers=headers, json=payload)
    except (OSError, httpx.HTTPError) as exc:
        logger.warning(
            "helm_voice_speak_backend_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503, detail="voice_synthesis_backend_unavailable"
        ) from exc

    if response.status_code in {401, 403}:
        logger.warning(
            "helm_voice_speak_backend_rejected",
            extra={"backend_status": response.status_code},
        )
        raise HTTPException(status_code=502, detail="voice_synthesis_backend_rejected")
    if response.status_code >= 400:
        logger.warning(
            "helm_voice_speak_backend_failed",
            extra={"backend_status": response.status_code},
        )
        raise HTTPException(status_code=502, detail="voice_synthesis_backend_failed")

    audio = response.content
    if not audio:
        logger.warning("helm_voice_speak_empty_audio")
        raise HTTPException(status_code=502, detail="voice_synthesis_empty_audio")
    if len(audio) > MAX_VOICE_AUDIO_BYTES:
        logger.warning(
            "helm_voice_speak_audio_too_large",
            extra={"bytes": len(audio)},
        )
        raise HTTPException(status_code=502, detail="voice_synthesis_audio_too_large")

    voice = response.headers.get("x-jarvis-voice", "")
    headers_out = {"Cache-Control": "no-store"}
    if voice:
        headers_out["X-Jarvis-Voice"] = voice

    logger.info("helm_voice_speak_ok", extra={"bytes": len(audio)})
    return Response(content=audio, media_type="audio/wav", headers=headers_out)


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


@router.post("/voice/speak")
async def helm_voice_speak(
    request: Request,
    body: HelmVoiceSpeakRequest,
    _user_id: str = Depends(require_auth),
) -> Response:
    """Synthesize a short Helm AT-0 reply through the configured voice backend."""

    check_scopes(request, "helm.read", "admin")
    return await _forward_voice_speak(body)
