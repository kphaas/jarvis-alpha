"""Unit tests for Brain → Gateway LLM transport."""

from unittest.mock import patch

import pytest

from brain.services.llm_transport import (
    GatewayTransportError,
    call_gateway_cloud,
)


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("ALPHA_BRAIN_SERVICE_TOKEN", "test-token")


async def test_missing_token_raises(monkeypatch):
    monkeypatch.delenv("GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("ALPHA_BRAIN_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("ALPHA_SERVICE_TOKEN", raising=False)
    with pytest.raises(GatewayTransportError, match="ALPHA_SERVICE_TOKEN not set"):
        await call_gateway_cloud(
            provider="anthropic",
            model="claude-haiku",
            system_prompt="sys",
            user_message="hi",
        )


async def test_success_claude_shape():
    """Gateway returns {provider, result} envelope. Claude result has content[0].text."""
    response_body = (
        '{"provider":"claude",'
        '"result":{"content":[{"type":"text","text":"hello world"}]}}'
    )
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, response_body),
    ):
        text = await call_gateway_cloud(
            provider="anthropic",
            model="claude-haiku",
            system_prompt="sys",
            user_message="hi",
        )
    assert text == "hello world"


async def test_success_gemini_shape():
    """Gemini result shape: candidates[0].content.parts[0].text"""
    response_body = (
        '{"provider":"gemini",'
        '"result":{"candidates":[{"content":{"parts":[{"text":"gemini reply"}]}}]}}'
    )
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, response_body),
    ):
        text = await call_gateway_cloud(
            provider="google",
            model="gemini-flash",
            system_prompt="sys",
            user_message="hi",
        )
    assert text == "gemini reply"


async def test_curl_failure():
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(7, ""),
    ):
        with pytest.raises(GatewayTransportError, match="curl failed"):
            await call_gateway_cloud(
                provider="anthropic",
                model="x",
                system_prompt="",
                user_message="",
            )


async def test_non_json_response():
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, "not json"),
    ):
        with pytest.raises(GatewayTransportError, match="non-JSON"):
            await call_gateway_cloud(
                provider="anthropic",
                model="x",
                system_prompt="",
                user_message="",
            )


async def test_gateway_fastapi_error():
    """FastAPI errors come back as {'detail': ...} with no 'result' field."""
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, '{"detail":"rate limited"}'),
    ):
        with pytest.raises(GatewayTransportError, match="rate limited"):
            await call_gateway_cloud(
                provider="anthropic",
                model="x",
                system_prompt="",
                user_message="",
            )


async def test_missing_result_field():
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, '{"status":"ok"}'),
    ):
        with pytest.raises(GatewayTransportError, match="missing result"):
            await call_gateway_cloud(
                provider="anthropic",
                model="x",
                system_prompt="",
                user_message="",
            )


async def test_extract_text_empty_claude_content():
    """Claude result with empty content list → extract_text returns '' → error raised."""
    response_body = '{"provider":"claude","result":{"content":[]}}'
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, response_body),
    ):
        with pytest.raises(GatewayTransportError, match="Could not extract text"):
            await call_gateway_cloud(
                provider="anthropic",
                model="x",
                system_prompt="",
                user_message="",
            )
