from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from brain.services.internet_scout.models import (
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutRequest,
    SourceReference,
)
from brain.services.internet_scout.policy import evaluate_policy
from brain.services.internet_scout.repository import InternetScoutRepository


class FakeConn:
    def __init__(self) -> None:
        self.request_id = uuid4()
        self.source_id = uuid4()
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        if "INSERT INTO public.alpha_internet_requests" in query:
            return {"id": self.request_id}
        if "INSERT INTO public.alpha_internet_sources" in query:
            return {"id": self.source_id}
        if "FROM public.alpha_internet_requests" in query:
            return {
                "requester": "test",
                "request_shape": {
                    "max_pages": 1,
                    "max_depth": 0,
                    "needs_interaction": False,
                    "sensitivity": "normal",
                },
            }
        raise AssertionError(query)

    async def execute(self, query: str, *args: object) -> None:
        self.execute_calls.append((query, args))

    async def fetch(self, query: str, *args: object):
        self.fetch_calls.append((query, args))
        if "FROM public.alpha_internet_sources" in query:
            return [
                {
                    "id": self.source_id,
                    "url": "https://public.example.test/report",
                    "host": "public.example.test",
                    "title": "Report",
                    "content_hash": "a" * 64,
                    "fetched_at": datetime.now(UTC),
                }
            ]
        if "FROM public.alpha_internet_evidence" in query:
            return [
                {
                    "source_url": "https://public.example.test/report",
                    "claim": "Claim",
                    "citation_text": "Citation",
                    "confidence": "medium",
                }
            ]
        raise AssertionError(query)


@pytest.mark.asyncio
async def test_repository_stores_request_without_raw_query_in_shape():
    conn = FakeConn()
    repo = InternetScoutRepository(conn)
    request = InternetScoutRequest(query="sensitive raw query", requester="test")
    decision = evaluate_policy(request)

    request_id = await repo.create_request(
        user_id="ken",
        request=request,
        decision=decision,
    )

    assert request_id == conn.request_id
    insert_args = conn.fetchrow_calls[0][1]
    assert insert_args[6].startswith("sha256:")
    assert "sensitive raw query" not in str(insert_args[7])
    assert '"has_query": true' in str(insert_args[7])


@pytest.mark.asyncio
async def test_repository_stores_packet_sources_claims_and_events():
    conn = FakeConn()
    repo = InternetScoutRepository(conn)
    packet = InternetEvidencePacket(
        request=InternetScoutRequest(query="beacon"),
        sources=[
            SourceReference(
                url="https://public.example.test/report",
                host="public.example.test",
                title="Report",
                content_hash="a" * 64,
            )
        ],
        claims=[
            EvidenceClaim(
                claim="Claim",
                source_url="https://public.example.test/report",
                citation_text="Citation",
            )
        ],
    )

    await repo.store_packet(request_id=conn.request_id, packet=packet)
    await repo.record_tool_event(
        request_id=conn.request_id,
        tool="search",
        event_type="gateway_call",
        status="succeeded",
    )

    assert isinstance(conn.source_id, UUID)
    assert any("alpha_internet_evidence" in call[0] for call in conn.execute_calls)
    assert any("alpha_internet_tool_events" in call[0] for call in conn.execute_calls)


@pytest.mark.asyncio
async def test_repository_loads_stored_packet():
    conn = FakeConn()
    packet = await InternetScoutRepository(conn).load_packet(conn.request_id)

    assert packet is not None
    assert packet.sources[0].url == "https://public.example.test/report"
    assert packet.claims[0].citation_text == "Citation"
