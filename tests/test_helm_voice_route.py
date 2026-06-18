from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route
from brain.routes import helm_voice


def _request(*, scopes: list[str] | None = None, jwt_token: str = "alpha-token"):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_id="ken",
            role="user",
            actor_type="user",
            scopes=scopes or [],
            jwt_token=jwt_token,
        )
    )


class FakeUpload:
    def __init__(
        self,
        data: bytes,
        *,
        content_type: str = "audio/webm",
        filename: str = "clip.webm",
    ) -> None:
        self._data = data
        self.content_type = content_type
        self.filename = filename

    async def read(self, _size: int = -1) -> bytes:
        return self._data


def test_helm_voice_route_is_t2_security_write_classified() -> None:
    assert classify_route("POST", "/v1/helm/voice/transcribe") == [
        "write",
        "security_write",
    ]


@pytest.mark.asyncio
async def test_helm_voice_requires_helm_read_scope() -> None:
    with pytest.raises(HTTPException) as exc:
        await helm_voice.helm_voice_transcribe(
            _request(),
            FakeUpload(b"audio"),
            _user_id="ken",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["required_scopes"] == ["helm.read", "admin"]


@pytest.mark.asyncio
async def test_helm_voice_fails_closed_when_backend_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JARVIS_HELM_VOICE_TRANSCRIBE_URL", raising=False)

    with pytest.raises(HTTPException) as exc:
        await helm_voice.helm_voice_transcribe(
            _request(scopes=["helm.read"]),
            FakeUpload(b"audio"),
            _user_id="ken",
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "voice_transcription_unconfigured"


@pytest.mark.asyncio
async def test_helm_voice_rejects_unsupported_audio_type() -> None:
    with pytest.raises(HTTPException) as exc:
        await helm_voice.helm_voice_transcribe(
            _request(scopes=["helm.read"]),
            FakeUpload(b"not-audio", content_type="text/plain", filename="clip.txt"),
            _user_id="ken",
        )

    assert exc.value.status_code == 415
    assert exc.value.detail == "unsupported_audio_type"


@pytest.mark.asyncio
async def test_helm_voice_forwards_recording_to_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"text": "Hello AT-0", "language": "en"}

    class FakeClient:
        def __init__(self, *, timeout: float, verify: bool) -> None:
            calls["timeout"] = timeout
            calls["verify"] = verify

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            files: dict[str, tuple[str, bytes, str]],
        ) -> FakeResponse:
            calls["url"] = url
            calls["headers"] = headers
            calls["files"] = files
            return FakeResponse()

    monkeypatch.setenv(
        "JARVIS_HELM_VOICE_TRANSCRIBE_URL",
        "http://127.0.0.1:4211/transcribe",
    )
    monkeypatch.setenv("JARVIS_HELM_VOICE_VERIFY_TLS", "false")
    monkeypatch.setenv("JARVIS_HELM_VOICE_BACKEND_TOKEN", "voice-backend-token")
    monkeypatch.setattr(helm_voice.httpx, "AsyncClient", FakeClient)

    response = await helm_voice.helm_voice_transcribe(
        _request(scopes=["helm.read"], jwt_token="browser-token"),
        FakeUpload(b"fake-audio", content_type="audio/webm;codecs=opus"),
        _user_id="ken",
    )

    assert response == {
        "text": "Hello AT-0",
        "language": "en",
        "source": "alpha_helm_voice_gate",
    }
    assert calls["url"] == "http://127.0.0.1:4211/transcribe"
    assert calls["verify"] is False
    assert calls["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer voice-backend-token",
    }
    assert calls["files"] == {"audio": ("clip.webm", b"fake-audio", "audio/webm")}


@pytest.mark.asyncio
async def test_helm_voice_falls_back_to_alpha_session_token_for_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"transcript": "Use the Alpha session"}

    class FakeClient:
        def __init__(self, *, timeout: float, verify: bool) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            files: dict[str, tuple[str, bytes, str]],
        ) -> FakeResponse:
            calls["headers"] = headers
            calls["files"] = files
            return FakeResponse()

    monkeypatch.setenv("JARVIS_HELM_VOICE_TRANSCRIBE_URL", "http://voice/transcribe")
    monkeypatch.delenv("JARVIS_HELM_VOICE_BACKEND_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_HELM_VOICE_BACKEND_TOKEN_SECRET", raising=False)
    monkeypatch.setattr(helm_voice.httpx, "AsyncClient", FakeClient)

    response = await helm_voice.helm_voice_transcribe(
        _request(scopes=["helm.read"], jwt_token="alpha-session-token"),
        FakeUpload(b"fake-audio"),
        _user_id="ken",
    )

    assert response["text"] == "Use the Alpha session"
    assert calls["headers"]["Authorization"] == "Bearer alpha-session-token"



def test_helm_voice_speak_route_is_t2_security_write_classified() -> None:
    assert classify_route("POST", "/v1/helm/voice/speak") == [
        "write",
        "security_write",
    ]


@pytest.mark.asyncio
async def test_helm_voice_speak_requires_helm_read_scope() -> None:
    with pytest.raises(HTTPException) as exc:
        await helm_voice.helm_voice_speak(
            _request(),
            helm_voice.HelmVoiceSpeakRequest(text="Hello AT-0"),
            _user_id="ken",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["required_scopes"] == ["helm.read", "admin"]


@pytest.mark.asyncio
async def test_helm_voice_speak_fails_closed_when_backend_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JARVIS_HELM_VOICE_SPEAK_URL", raising=False)

    with pytest.raises(HTTPException) as exc:
        await helm_voice.helm_voice_speak(
            _request(scopes=["helm.read"]),
            helm_voice.HelmVoiceSpeakRequest(text="Hello AT-0"),
            _user_id="ken",
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "voice_synthesis_unconfigured"


@pytest.mark.asyncio
async def test_helm_voice_speak_forwards_text_to_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        content = b"RIFFfake-wav"
        headers = {"x-jarvis-voice": "alloy"}

    class FakeClient:
        def __init__(self, *, timeout: float, verify: bool) -> None:
            calls["timeout"] = timeout
            calls["verify"] = verify

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> FakeResponse:
            calls["url"] = url
            calls["headers"] = headers
            calls["json"] = json
            return FakeResponse()

    monkeypatch.setenv(
        "JARVIS_HELM_VOICE_SPEAK_URL",
        "http://127.0.0.1:4211/speak",
    )
    monkeypatch.setenv("JARVIS_HELM_VOICE_VERIFY_TLS", "false")
    monkeypatch.setenv("JARVIS_HELM_VOICE_SPEAK_BACKEND_TOKEN", "speak-token")
    monkeypatch.delenv("JARVIS_HELM_VOICE_SPEAK_BACKEND_TOKEN_SECRET", raising=False)
    monkeypatch.setattr(helm_voice.httpx, "AsyncClient", FakeClient)

    response = await helm_voice.helm_voice_speak(
        _request(scopes=["helm.read"]),
        helm_voice.HelmVoiceSpeakRequest(text="Hello AT-0", voice="alloy", speed=1.1),
        _user_id="ken",
    )

    assert response.media_type == "audio/wav"
    assert response.body == b"RIFFfake-wav"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Jarvis-Voice"] == "alloy"
    assert calls["url"] == "http://127.0.0.1:4211/speak"
    assert calls["verify"] is False
    assert calls["headers"] == {
        "Accept": "audio/wav",
        "Authorization": "Bearer speak-token",
    }
    assert calls["json"] == {
        "text": "Hello AT-0",
        "speed": 1.1,
        "voice": "alloy",
    }
