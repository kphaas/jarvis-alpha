from __future__ import annotations

import json
from uuid import UUID

import pytest

from brain.services.herald_interaction_ledger import record_social_draft_interaction


@pytest.mark.asyncio
async def test_social_draft_interaction_strips_raw_topic_from_spark_payload() -> None:
    calls: list[tuple[object, ...]] = []

    class FakeConn:
        async def execute(self, _query: str, *params: object):
            calls.append(params)
            return "INSERT 0 1"

    await record_social_draft_interaction(
        FakeConn(),  # type: ignore[arg-type]
        request_id=UUID("11111111-1111-4111-8111-111111111111"),
        variant_id=UUID("22222222-2222-4222-8222-222222222222"),
        event_type="variant_created",
        actor_sub="ken",
        actor_type="human",
        payload={
            "platform": "linkedin",
            "draft_kind": "post",
            "spark_input": {
                "topic": "raw user topic should not enter ledger metadata",
                "context_hash": "abc",
                "context_available": True,
            },
        },
    )

    params = calls[0]
    assert params[0:5] == (
        "linkedin",
        "draft",
        "internal",
        "variant_created",
        "created",
    )
    metadata = json.loads(params[-1])
    assert metadata["spark_input"] == {
        "context_hash": "abc",
        "context_available": True,
    }
    assert "raw user topic" not in params[-1]
