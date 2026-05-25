import httpx
import pytest

from gateway.adapters.gemini_adapter import GeminiAdapter, _to_gemini_payload


def test_to_gemini_payload_translates_common_chat_shape():
    model, payload = _to_gemini_payload(
        {
            "model": "gemini-2.5-flash",
            "system": "review safely",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 2000,
            "temperature": 0.2,
        }
    )

    assert model == "gemini-2.5-flash"
    assert payload == {
        "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
        "systemInstruction": {"parts": [{"text": "review safely"}]},
        "generationConfig": {
            "maxOutputTokens": 2000,
            "temperature": 0.2,
        },
    }


def test_to_gemini_payload_preserves_native_contents():
    model, payload = _to_gemini_payload(
        {
            "model": "gemini-2.5-flash",
            "contents": [{"role": "user", "parts": [{"text": "native"}]}],
        }
    )

    assert model == "gemini-2.5-flash"
    assert payload == {"contents": [{"role": "user", "parts": [{"text": "native"}]}]}


async def test_gemini_adapter_sanitizes_http_errors(monkeypatch):
    calls = {}

    class FakeResponse:
        status_code = 400
        text = '{"error":{"message":"bad request"}}'

        def raise_for_status(self):
            request = httpx.Request(
                "POST",
                "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=secret-key",
            )
            raise httpx.HTTPStatusError(
                "request failed with secret-key",
                request=request,
                response=httpx.Response(self.status_code, text=self.text),
            )

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, json, params):
            calls["url"] = url
            calls["json"] = json
            calls["params"] = params
            return FakeResponse()

    monkeypatch.setattr(
        "gateway.adapters.gemini_adapter.get_secret", lambda name: "secret-key"
    )
    monkeypatch.setattr("gateway.adapters.gemini_adapter.httpx.AsyncClient", FakeClient)

    with pytest.raises(RuntimeError) as exc:
        await GeminiAdapter().call(
            {
                "model": "gemini-2.5-flash",
                "system": "sys",
                "messages": [{"role": "user", "content": "hi"}],
            }
        )

    assert "secret-key" not in str(exc.value)
    assert "Gemini API status=400" in str(exc.value)
    assert calls["json"]["contents"][0]["parts"][0]["text"] == "hi"
