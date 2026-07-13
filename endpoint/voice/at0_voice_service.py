"""Endpoint-local AT-0 speech-to-text worker.

This service is intentionally narrow. Helm never calls it directly; Alpha's
`/v1/helm/voice/transcribe` gate owns browser auth and forwards short audio
clips here with a backend bearer token.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Iterable, Optional, Protocol

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from pydantic import BaseModel

SERVICE_NAME = "at0-voice"
DEFAULT_MODEL_PATH = "~/jarvis/models/faster-whisper-base.en"
REQUIRED_MODEL_FILES = ("config.json", "model.bin")
DEFAULT_MAX_AUDIO_BYTES = 8 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/aac",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "application/octet-stream",
}

logger = logging.getLogger(SERVICE_NAME)
if not logger.handlers:
    logging.basicConfig(
        level=os.getenv("JARVIS_AT0_VOICE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

app = FastAPI(title="AT-0 Voice Worker", version="0.1.0")


class VoiceRuntimeUnavailable(RuntimeError):
    """Raised when local transcription runtime is not ready."""


class Segment(Protocol):
    text: str


class TranscriptionInfo(Protocol):
    language: str


class WhisperModel(Protocol):
    def transcribe(
        self,
        audio: str,
        *,
        beam_size: int,
        language: str,
        vad_filter: bool,
        condition_on_previous_text: bool,
    ) -> tuple[Iterable[Segment], TranscriptionInfo]:
        """Transcribe a local audio file."""


class HealthResponse(BaseModel):
    status: str
    service: str
    auth_configured: bool
    stt_available: bool
    model_path: str
    ffmpeg_available: bool
    reason: Optional[str] = None


class TranscribeResponse(BaseModel):
    text: str
    language: str
    source: str
    latency_ms: int


_model: Optional[WhisperModel] = None
_model_lock = asyncio.Lock()


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return min(max(int(raw), minimum), maximum)
    except ValueError:
        return default


def _backend_token() -> Optional[str]:
    token = os.getenv("JARVIS_AT0_VOICE_BACKEND_TOKEN", "").strip()
    return token or None


def _model_path() -> Path:
    configured = os.getenv("JARVIS_AT0_VOICE_MODEL_PATH", DEFAULT_MODEL_PATH).strip()
    return Path(configured).expanduser()


def _max_audio_bytes() -> int:
    return _env_int(
        "JARVIS_AT0_VOICE_MAX_AUDIO_BYTES",
        DEFAULT_MAX_AUDIO_BYTES,
        minimum=1024,
        maximum=32 * 1024 * 1024,
    )


def _ffmpeg_bin() -> str:
    return os.getenv("JARVIS_AT0_VOICE_FFMPEG", "ffmpeg").strip() or "ffmpeg"


def _ffmpeg_timeout_secs() -> int:
    return _env_int("JARVIS_AT0_VOICE_FFMPEG_TIMEOUT_SECS", 20, minimum=3, maximum=120)


def _audio_content_type(file: UploadFile) -> str:
    return (file.content_type or "application/octet-stream").split(";", 1)[0].strip()


def _verify_authorization(authorization: Optional[str]) -> None:
    expected = _backend_token()
    if not expected:
        logger.warning("at0_voice_rejected auth_unconfigured")
        raise HTTPException(status_code=503, detail="voice_backend_auth_unconfigured")

    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        logger.warning("at0_voice_rejected auth_missing")
        raise HTTPException(status_code=401, detail="voice_backend_auth_required")

    token = authorization[len(prefix) :].strip()
    if token != expected:
        logger.warning("at0_voice_rejected auth_invalid")
        raise HTTPException(status_code=403, detail="voice_backend_auth_invalid")


def _runtime_status() -> tuple[bool, Optional[str]]:
    model_path = _model_path()
    if not model_path.exists():
        return False, "model_path_missing"
    if any(not (model_path / filename).is_file() for filename in REQUIRED_MODEL_FILES):
        return False, "model_files_missing"
    if shutil.which(_ffmpeg_bin()) is None:
        return False, "ffmpeg_missing"
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False, "faster_whisper_missing"
    return True, None


async def _get_model() -> WhisperModel:
    global _model
    if _model is not None:
        return _model

    async with _model_lock:
        if _model is not None:
            return _model

        ready, reason = _runtime_status()
        if not ready:
            raise VoiceRuntimeUnavailable(reason or "runtime_unavailable")

        from faster_whisper import WhisperModel as FasterWhisperModel

        try:
            model = await asyncio.to_thread(
                FasterWhisperModel,
                str(_model_path()),
                device=os.getenv("JARVIS_AT0_VOICE_DEVICE", "cpu"),
                compute_type=os.getenv("JARVIS_AT0_VOICE_COMPUTE_TYPE", "int8"),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error(
                "at0_voice_model_load_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise VoiceRuntimeUnavailable("model_load_failed") from exc
        _model = model
        logger.info("at0_voice_model_loaded", extra={"model_path": str(_model_path())})
        return _model


async def _read_upload(file: UploadFile) -> tuple[bytes, str, str]:
    content_type = _audio_content_type(file)
    if content_type not in ALLOWED_AUDIO_TYPES:
        logger.warning(
            "at0_voice_rejected unsupported_audio_type",
            extra={"content_type": content_type},
        )
        raise HTTPException(status_code=415, detail="unsupported_audio_type")

    data = await file.read(_max_audio_bytes() + 1)
    if not data:
        logger.warning("at0_voice_rejected empty_audio")
        raise HTTPException(status_code=400, detail="audio_file_empty")
    if len(data) > _max_audio_bytes():
        logger.warning("at0_voice_rejected audio_too_large", extra={"bytes": len(data)})
        raise HTTPException(status_code=413, detail="audio_file_too_large")

    suffix = Path(file.filename or "clip.webm").suffix or ".webm"
    return data, suffix, content_type


def _convert_to_wav(input_path: Path, output_path: Path) -> None:
    command = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(output_path),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            timeout=_ffmpeg_timeout_secs(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.TimeoutExpired as exc:
        raise VoiceRuntimeUnavailable("ffmpeg_timeout") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise VoiceRuntimeUnavailable("ffmpeg_failed") from exc


async def _transcribe_wav(wav_path: Path) -> tuple[str, str]:
    model = await _get_model()

    def run_transcribe() -> tuple[str, str]:
        segments, info = model.transcribe(
            str(wav_path),
            beam_size=5,
            language="en",
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text, getattr(info, "language", "en") or "en"

    return await asyncio.to_thread(run_transcribe)


async def _transcribe_upload(file: UploadFile) -> TranscribeResponse:
    started = time.perf_counter()
    data, suffix, content_type = await _read_upload(file)

    with tempfile.TemporaryDirectory(prefix="jarvis_at0_voice_") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / f"input{suffix}"
        output_path = temp_path / "audio.wav"
        input_path.write_bytes(data)
        await asyncio.to_thread(_convert_to_wav, input_path, output_path)
        text, language = await _transcribe_wav(output_path)

    if not text:
        logger.warning(
            "at0_voice_empty_transcript", extra={"content_type": content_type}
        )
        raise HTTPException(status_code=422, detail="voice_backend_empty_transcript")

    latency_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "at0_voice_transcribe_ok",
        extra={
            "bytes": len(data),
            "content_type": content_type,
            "language": language,
            "latency_ms": latency_ms,
        },
    )
    return TranscribeResponse(
        text=text,
        language=language,
        source="at0_endpoint_voice_worker",
        latency_ms=latency_ms,
    )


@app.get("/health")
async def health() -> HealthResponse:
    ready, reason = _runtime_status()
    auth_configured = _backend_token() is not None
    status = "ok" if auth_configured and ready else "degraded"
    return HealthResponse(
        status=status,
        service=SERVICE_NAME,
        auth_configured=auth_configured,
        stt_available=ready,
        model_path=str(_model_path()),
        ffmpeg_available=shutil.which(_ffmpeg_bin()) is not None,
        reason=reason,
    )


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    authorization: Optional[str] = Header(default=None),
) -> TranscribeResponse:
    _verify_authorization(authorization)
    try:
        return await _transcribe_upload(audio)
    except VoiceRuntimeUnavailable as exc:
        logger.warning("at0_voice_runtime_unavailable", extra={"reason": str(exc)})
        raise HTTPException(
            status_code=503, detail="voice_backend_unavailable"
        ) from exc
