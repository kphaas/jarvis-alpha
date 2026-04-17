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
    monkeypatch.delenv("ALPHA_BRAIN_SERVICE_TOKEN", raising=False)
    with pytest.raises(GatewayTransportError, match="SERVICE_TOKEN not set"):
        await call_gateway_cloud(
            provider="anthropic",
            model="claude-haiku",
            system_prompt="sys",
            user_message="hi",
        )


async def test_success():
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, '{"content":"hello world"}'),
    ):
        text = await call_gateway_cloud(
            provider="anthropic",
            model="claude-haiku",
            system_prompt="sys",
            user_message="hi",
        )
    assert text == "hello world"


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


async def test_gateway_error_response():
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, '{"error":"rate limited"}'),
    ):
        with pytest.raises(GatewayTransportError, match="rate limited"):
            await call_gateway_cloud(
                provider="anthropic",
                model="x",
                system_prompt="",
                user_message="",
            )


async def test_missing_text_field():
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, '{"status":"ok"}'),
    ):
        with pytest.raises(GatewayTransportError, match="missing text"):
            await call_gateway_cloud(
                provider="anthropic",
                model="x",
                system_prompt="",
                user_message="",
            )


async def test_alternative_text_fields():
    for field in ("content", "text", "completion"):
        with patch(
            "brain.services.llm_transport._post_sync",
            return_value=(0, f'{{"{field}":"response"}}'),
        ):
            text = await call_gateway_cloud(
                provider="anthropic",
                model="x",
                system_prompt="",
                user_message="",
            )
            assert text == "response"
