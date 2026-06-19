from __future__ import annotations

import json
from uuid import UUID

import pytest

from brain.services.at0_mail_sender import prepare_at0_mail_reply_send


@pytest.mark.asyncio
async def test_prepare_send_records_audit_metadata_without_reply_body() -> None:
    draft_id = UUID("11111111-1111-4111-8111-111111111111")
    message_id = UUID("22222222-2222-4222-8222-222222222222")
    execute_calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeConn:
        async def fetchrow(self, query: str, *params):
            if "SELECT d.id" in query:
                return {
                    "id": draft_id,
                    "mail_message_id": message_id,
                    "mailbox": "hello@at-0.com",
                    "proposed_body": "Approved reply body",
                    "status": "approved",
                    "send_attempt_count": 0,
                    "graph_message_id": "graph-message-1",
                }
            if "RETURNING send_attempt_count" in query:
                return {"send_attempt_count": 1}
            raise AssertionError(f"unexpected query: {query}")

        async def execute(self, query: str, *params):
            execute_calls.append((query, params))
            return "INSERT 0 1"

    prepared = await prepare_at0_mail_reply_send(
        FakeConn(),
        draft_id=draft_id,
        actor_sub="ken",
        actor_type="human",
    )

    assert prepared.send_attempt_count == 1
    insert_call = execute_calls[-1]
    assert "alpha_at0_mail_send_events" in insert_call[0]
    event_payload = json.loads(insert_call[1][-1])
    assert event_payload["provider_operation"] == "message.reply"
    assert event_payload["send_attempt_count"] == 1
    assert event_payload["reply_body_hash"].startswith("sha256:")
    assert "Approved reply body" not in insert_call[1][-1]
