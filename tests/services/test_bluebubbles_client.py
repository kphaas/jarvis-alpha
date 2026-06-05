from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from brain.services.bluebubbles_client import (
    BlueBubblesPolicyError,
    BlueBubblesReadOnlyClient,
    load_spark_bluebubbles_policy,
)


def _write_policy_tree(
    root: Path,
    *,
    connector_mode: str = "read_only",
    approved_message_query: bool = False,
) -> None:
    (root / "spark" / "connectors").mkdir(parents=True)
    (root / "spark" / "policies").mkdir(parents=True)
    allowed_operations = (
        """
allowed_operations:
  - POST /api/v1/message/query for approved chat GUIDs only
"""
        if approved_message_query
        else ""
    )
    (root / "spark" / "connectors" / "bluebubbles.yml").write_text(
        f"""
version: 0.1.0
mode: {connector_mode}
{allowed_operations}
blocked_operations:
  - POST /api/v1/message/text
  - POST /api/v1/message/attachment
  - POST /api/v1/message/multipart
thread_access:
  default: denied
data_handling:
  log_message_bodies: false
  log_contact_names: false
  store_raw_threads: false
""",
        encoding="utf-8",
    )
    (root / "spark" / "policies" / "message_drafting.yml").write_text(
        """
current_mode: draft_only
modes:
  draft_only:
    can_send: false
""",
        encoding="utf-8",
    )
    (root / "spark" / "policies" / "memory_rules.yml").write_text(
        """
draft_context:
  durable_write: false
redaction_policy:
  third_party_message_text: runtime_only
""",
        encoding="utf-8",
    )


def test_policy_loader_accepts_read_only_bluebubbles_contract(tmp_path: Path) -> None:
    _write_policy_tree(tmp_path)

    policy = load_spark_bluebubbles_policy(tmp_path)

    assert policy.connector_mode == "read_only"
    assert policy.drafting_mode == "draft_only"
    assert policy.thread_default == "denied"


def test_policy_loader_fails_closed_if_connector_is_not_read_only(
    tmp_path: Path,
) -> None:
    _write_policy_tree(tmp_path, connector_mode="write_enabled")

    with pytest.raises(BlueBubblesPolicyError, match="read_only"):
        load_spark_bluebubbles_policy(tmp_path)


@pytest.mark.asyncio
async def test_health_suppresses_detected_account_values(tmp_path: Path) -> None:
    _write_policy_tree(tmp_path)
    policy = load_spark_bluebubbles_policy(tmp_path)
    seen_queries: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(str(request.url.query))
        return httpx.Response(
            200,
            json={
                "status": 200,
                "message": "Success",
                "data": {
                    "computer_id": "spark@jarvis-brain",
                    "os_version": "26.5.1",
                    "server_version": "1.9.9",
                    "private_api": False,
                    "proxy_service": "Dynamic DNS",
                    "helper_connected": False,
                    "detected_icloud": "ken@example.com",
                    "detected_imessage": "ken@example.com",
                },
            },
        )

    client = BlueBubblesReadOnlyClient(
        base_url="http://127.0.0.1:1234",
        password="secret",
        policy=policy,
        transport=httpx.MockTransport(handler),
    )

    health = await client.health()

    assert health.status == "Success"
    assert health.detected_icloud is True
    assert health.detected_imessage is True
    assert "ken@example.com" not in json.dumps(asdict(health))
    assert seen_queries == ["b'password=secret'"]


@pytest.mark.asyncio
async def test_counts_and_recent_chats_return_metadata_only(tmp_path: Path) -> None:
    _write_policy_tree(tmp_path)
    policy = load_spark_bluebubbles_policy(tmp_path)
    requested_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/api/v1/chat/count":
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "message": "Success",
                    "data": {
                        "total": 1218,
                        "breakdown": {"iMessage": 484, "SMS": 706, "RCS": 28},
                    },
                },
            )
        if request.url.path == "/api/v1/message/count/me":
            return httpx.Response(
                200,
                json={"status": 200, "message": "Success", "data": {"total": 3496}},
            )
        if request.url.path == "/api/v1/chat/query":
            assert request.method == "POST"
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "message": "Success",
                    "metadata": {"count": 5, "total": 1218, "offset": 0, "limit": 5},
                    "data": [
                        {"guid": "chat-1", "displayName": "Do Not Return"},
                        {"guid": "chat-2", "lastMessage": "Do Not Return"},
                    ],
                },
            )
        return httpx.Response(404, json={"status": 404})

    client = BlueBubblesReadOnlyClient(
        base_url="http://127.0.0.1:1234",
        password="secret",
        policy=policy,
        transport=httpx.MockTransport(handler),
    )

    counts = await client.counts()
    metadata = await client.recent_chat_metadata(limit=5)

    assert counts.total_chats == 1218
    assert counts.sent_messages == 3496
    assert metadata.total == 1218
    assert metadata.data_count == 2
    assert requested_paths == [
        "/api/v1/chat/count",
        "/api/v1/message/count/me",
        "/api/v1/chat/query",
    ]


@pytest.mark.asyncio
async def test_approved_messages_for_chat_reads_bodies_only_when_policy_allows(
    tmp_path: Path,
) -> None:
    _write_policy_tree(tmp_path, approved_message_query=True)
    policy = load_spark_bluebubbles_policy(tmp_path)
    seen_payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/message/query"
        assert request.method == "POST"
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "status": 200,
                "message": "Success",
                "data": [
                    {
                        "guid": "message-1",
                        "text": "private inbound body",
                        "isFromMe": False,
                        "dateCreated": "2026-06-05T10:00:00Z",
                    },
                    {
                        "guid": "message-2",
                        "message": "ken sent body",
                        "isFromMe": True,
                    },
                    {"guid": "message-3", "text": ""},
                ],
            },
        )

    client = BlueBubblesReadOnlyClient(
        base_url="http://127.0.0.1:1234",
        password="secret",
        policy=policy,
        transport=httpx.MockTransport(handler),
    )

    messages = await client.approved_messages_for_chat(
        chat_guid="approved-chat-guid",
        limit=3,
    )

    assert seen_payloads == [
        {
            "chatGuid": "approved-chat-guid",
            "offset": 0,
            "limit": 3,
            "sort": "dateCreated",
            "with": [],
        }
    ]
    assert len(messages) == 2
    assert messages[0].body_text == "private inbound body"
    assert messages[0].is_from_me is False
    assert messages[1].body_text == "ken sent body"
    assert messages[1].is_from_me is True
    assert "message-1" not in json.dumps([asdict(message) for message in messages])


@pytest.mark.asyncio
async def test_approved_messages_for_chat_fails_closed_without_policy_allowance(
    tmp_path: Path,
) -> None:
    _write_policy_tree(tmp_path, approved_message_query=False)
    policy = load_spark_bluebubbles_policy(tmp_path)
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"status": 200, "data": []})

    client = BlueBubblesReadOnlyClient(
        base_url="http://127.0.0.1:1234",
        password="secret",
        policy=policy,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(BlueBubblesPolicyError, match="message query"):
        await client.approved_messages_for_chat(chat_guid="approved-chat-guid")

    assert called is False
