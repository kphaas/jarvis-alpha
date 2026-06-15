from __future__ import annotations

from uuid import uuid4

import pytest

from brain.services.internet_scout.quality_canary import run_quality_canary_once


class FakeCanaryConn:
    def __init__(self) -> None:
        self.request_id = uuid4()
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        if "INSERT INTO public.alpha_internet_requests" in query:
            return {"id": self.request_id}
        raise AssertionError(f"unexpected query: {query}")

    async def execute(self, query: str, *args: object):
        self.execute_calls.append((query, args))
        if "INSERT INTO public.alpha_internet_tool_events" in query:
            return "INSERT 0 1"
        raise AssertionError(f"unexpected query: {query}")


@pytest.mark.asyncio
async def test_quality_canary_persists_redacted_metadata() -> None:
    conn = FakeCanaryConn()

    metadata = await run_quality_canary_once(conn)

    assert metadata["status"] == "passed"
    assert metadata["case_count"] >= 30
    assert metadata["failed"] == 0
    assert metadata["request_id"] == str(conn.request_id)
    assert conn.fetchrow_calls[0][1][0] == "system"
    assert conn.fetchrow_calls[0][1][1] == "alpha_beacon.quality_canary"
    event_args = conn.execute_calls[0][1]
    assert event_args[2] == "quality_canary"
    assert event_args[3] == "succeeded"
    assert "OpenAI charges $123" not in str(event_args)
