from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from endpoint.voice import at0_voice_service as service


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModel:
    def transcribe(
        self,
        audio: str,
        *,
        beam_size: int,
        language: str,
        vad_filter: bool,
        condition_on_previous_text: bool,
    ):
        assert audio.endswith("audio.wav")
        assert beam_size == 5
        assert language == "en"
        assert vad_filter is True
        assert condition_on_previous_text is False
        return [FakeSegment("Hello"), FakeSegment("AT-0")], SimpleNamespace(
            language="en"
        )


def _client(monkeypatch):
    service._model = None
    monkeypatch.setenv("JARVIS_AT0_VOICE_BACKEND_TOKEN", "backend-token")
    monkeypatch.setenv("JARVIS_AT0_VOICE_MODEL_PATH", "/tmp/fake-at0-model")
    monkeypatch.setattr(service, "_runtime_status", lambda: (True, None))
    return TestClient(service.app)


def test_health_reports_auth_and_runtime(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "at0-voice",
        "auth_configured": True,
        "stt_available": True,
        "model_path": "/tmp/fake-at0-model",
        "ffmpeg_available": service.shutil.which(service._ffmpeg_bin()) is not None,
        "reason": None,
    }


def test_default_model_path_stays_outside_git_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("JARVIS_AT0_VOICE_MODEL_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert service._model_path() == tmp_path / "jarvis/models/faster-whisper-base.en"


def test_runtime_status_rejects_incomplete_model_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    model_path = tmp_path / "model"
    model_path.mkdir()
    monkeypatch.setattr(service, "_model_path", lambda: model_path)

    assert service._runtime_status() == (False, "model_files_missing")


def test_get_model_wraps_model_load_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenWhisperModel:
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("broken model")

    service._model = None
    monkeypatch.setattr(service, "_runtime_status", lambda: (True, None))
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=BrokenWhisperModel),
    )

    with pytest.raises(service.VoiceRuntimeUnavailable, match="model_load_failed"):
        asyncio.run(service._get_model())


def test_transcribe_requires_backend_token(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/transcribe",
        files={"audio": ("clip.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "voice_backend_auth_required"


def test_transcribe_rejects_invalid_backend_token(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/transcribe",
        headers={"Authorization": "Bearer wrong"},
        files={"audio": ("clip.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "voice_backend_auth_invalid"


def test_transcribe_rejects_unsupported_audio_type(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/transcribe",
        headers={"Authorization": "Bearer backend-token"},
        files={"audio": ("clip.txt", b"not-audio", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "unsupported_audio_type"


def test_transcribe_returns_text(monkeypatch) -> None:
    client = _client(monkeypatch)

    async def fake_get_model() -> FakeModel:
        return FakeModel()

    monkeypatch.setattr(
        service, "_convert_to_wav", lambda _input, output: output.write_bytes(b"wav")
    )
    monkeypatch.setattr(service, "_get_model", fake_get_model)

    response = client.post(
        "/transcribe",
        headers={"Authorization": "Bearer backend-token"},
        files={"audio": ("clip.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "Hello AT-0"
    assert payload["language"] == "en"
    assert payload["source"] == "at0_endpoint_voice_worker"
    assert isinstance(payload["latency_ms"], int)


def test_transcribe_fails_closed_when_runtime_missing(monkeypatch) -> None:
    client = _client(monkeypatch)
    monkeypatch.setattr(
        service, "_runtime_status", lambda: (False, "model_path_missing")
    )

    response = client.post(
        "/transcribe",
        headers={"Authorization": "Bearer backend-token"},
        files={"audio": ("clip.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "voice_backend_unavailable"
