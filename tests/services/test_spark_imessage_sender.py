from __future__ import annotations

import json
from dataclasses import asdict

import httpx
import pytest

from brain.services.bluebubbles_client import BlueBubblesPolicyError
from brain.services.spark_imessage_sender import SparkIMessageSendClient


@pytest.mark.asyncio
async def test_send_client_fails_closed_when_not_enabled() -> None:
    client = SparkIMessageSendClient(
        base_url="http://127.0.0.1:1234",
        password="secret",
        send_enabled=False,
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    with pytest.raises(BlueBubblesPolicyError, match="disabled"):
        await client.send_text_to_chat(
            chat_guid="approved-chat-guid",
            text="Approved text",
        )


@pytest.mark.asyncio
async def test_send_client_posts_exact_text_to_bluebubbles() -> None:
    seen: list[tuple[str, dict[str, object], str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.path,
                json.loads(request.content.decode("utf-8")),
                str(request.url.query),
            )
        )
        return httpx.Response(
            200,
            json={
                "status": 200,
                "message": "Success",
                "data": {"guid": "private-message-guid"},
            },
        )

    client = SparkIMessageSendClient(
        base_url="http://127.0.0.1:1234",
        password="secret",
        send_enabled=True,
        transport=httpx.MockTransport(handler),
    )

    result = await client.send_text_to_chat(
        chat_guid="approved-chat-guid",
        text="Approved text",
    )

    assert result.status == 200
    assert result.message == "Success"
    assert result.message_ref_hash is not None
    assert "private-message-guid" not in json.dumps(asdict(result))
    assert seen == [
        (
            "/api/v1/message/text",
            {
                "chatGuid": "approved-chat-guid",
                "message": "Approved text",
                "tempGuid": seen[0][1]["tempGuid"],
            },
            "b'password=secret'",
        )
    ]
    assert str(seen[0][1]["tempGuid"]).startswith("temp-")


@pytest.mark.asyncio
async def test_send_client_uses_send_specific_endpoint_and_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), str(request.url.query)))
        return httpx.Response(
            200,
            json={
                "status": 200,
                "message": "Success",
                "data": {"guid": "private-message-guid"},
            },
        )

    monkeypatch.setenv("BLUEBUBBLES_BASE_URL", "http://127.0.0.1:1234")
    monkeypatch.setenv("BLUEBUBBLES_PASSWORD", "read-secret")
    monkeypatch.setenv("SPARK_IMESSAGE_SEND_BASE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("SPARK_IMESSAGE_SEND_PASSWORD", "send-secret")
    monkeypatch.setenv("SPARK_IMESSAGE_SEND_ENABLED", "true")

    client = SparkIMessageSendClient(transport=httpx.MockTransport(handler))

    result = await client.send_text_to_chat(
        chat_guid="approved-chat-guid",
        text="Approved text",
    )

    assert result.status == 200
    assert seen == [
        (
            "http://127.0.0.1:8765/api/v1/message/text?password=send-secret",
            "b'password=send-secret'",
        )
    ]
