from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route
from brain.routes import internet_scout
from brain.services.internet_scout.evidence import build_source_reference, content_hash
from brain.services.internet_scout.models import (
    BrowserRunObservation,
    BrowserSandboxPolicy,
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutHealthCheck,
    InternetScoutHealthResponse,
    InternetScoutBrowserRunRequest,
    InternetScoutBrowserRunResponse,
    InternetScoutConsumerRequest,
    InternetScoutMemoryPromotion,
    InternetScoutMemoryPromotionCandidate,
    InternetScoutMemoryPromotionCreateRequest,
    InternetScoutMemoryPromotionReviewRequest,
    InternetScoutRequest,
    InternetScoutRetentionDeleteRequest,
    InternetScoutRetentionDeleteResponse,
    InternetScoutRetentionReport,
    InternetTool,
)


def _request(*, scopes: list[str] | None = None, role: str = "user"):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_id="ken",
            role=role,
            actor_type="user",
            scopes=scopes or [],
        ),
        url=SimpleNamespace(path="/v1/internet-scout/research"),
    )


class FakeRepo:
    request_id = uuid4()
    created: list[object] = []
    events: list[dict[str, object]] = []
    stored: list[object] = []

    def __init__(self, conn) -> None:
        self.conn = conn

    async def create_request(self, **kwargs):
        self.created.append(kwargs)
        return self.request_id

    async def record_tool_event(self, **kwargs):
        self.events.append(kwargs)

    async def store_packet(self, **kwargs):
        self.stored.append(kwargs)

    async def mark_request_succeeded(self, request_id):
        self.events.append({"mark": "succeeded", "request_id": request_id})

    async def mark_request_failed(self, request_id, error_text):
        self.events.append(
            {"mark": "failed", "request_id": request_id, "error_text": error_text}
        )

    async def count_recent_browser_runs(self, user_id):
        return 0

    async def load_packet(self, request_id):
        source = build_source_reference(
            url="https://public.example.test/report",
            content="Stored Beacon source.",
        )
        return InternetEvidencePacket(
            request=InternetScoutRequest(requester="stored"),
            sources=[source],
            claims=[
                EvidenceClaim(
                    claim="Stored Beacon source.",
                    source_url=source.url,
                    citation_text="Stored Beacon source.",
                    confidence="medium",
                )
            ],
        )

    async def create_memory_promotions(self, **kwargs):
        self.created.append({"memory_promotions": kwargs})
        return [
            InternetScoutMemoryPromotion(
                id=uuid4(),
                request_id=kwargs["request_id"],
                target_user_id=kwargs["target_user_id"],
                requested_by=kwargs["requested_by"],
                source_url="https://public.example.test/report",
                source_host="public.example.test",
                source_content_hash="a" * 64,
                citation_text="Stored Beacon source.",
                proposed_fact=kwargs["candidates"][0].proposed_fact,
                category=kwargs["candidates"][0].category,
                status="pending_review",
                semantic_result={},
            )
        ]

    async def review_memory_promotion(self, **kwargs):
        self.events.append({"memory_review": kwargs})
        return InternetScoutMemoryPromotion(
            id=kwargs["promotion_id"],
            request_id=self.request_id,
            target_user_id=uuid4(),
            requested_by="ken",
            source_url="https://public.example.test/report",
            source_host="public.example.test",
            source_content_hash="a" * 64,
            citation_text="Stored Beacon source.",
            proposed_fact="Beacon has a reviewed fact.",
            category="project",
            status="promoted" if kwargs["decision"] == "approve" else "rejected",
            semantic_result={"saved": kwargs["decision"] == "approve"},
        )


class FakeExecutor:
    async def execute(self, body):
        source = build_source_reference(
            url="https://public.example.test/report",
            content="Beacon source.",
        )
        return None, InternetEvidencePacket(
            request=body,
            sources=[source],
            claims=[
                EvidenceClaim(
                    claim="Beacon source.",
                    source_url=source.url,
                    citation_text="Beacon source.",
                    confidence="medium",
                )
            ],
        )


@asynccontextmanager
async def fake_rls_connection(request):
    yield object()


@pytest.mark.asyncio
async def test_internet_scout_research_requires_scope():
    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_research(
            InternetScoutRequest(query="beacon"),
            _request(),
            _user_id="ken",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_internet_scout_research_stores_evidence(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(internet_scout, "InternetScoutExecutor", lambda: FakeExecutor())

    response = await internet_scout.internet_scout_research(
        InternetScoutRequest(query="beacon"),
        _request(scopes=["internet_scout.research"]),
        _user_id="ken",
    )

    assert response.request_id == FakeRepo.request_id
    assert response.evidence.sources[0].host == "public.example.test"
    assert FakeRepo.created[0]["user_id"] == "ken"
    assert any(event.get("status") == "succeeded" for event in FakeRepo.events)
    assert FakeRepo.stored


@pytest.mark.asyncio
async def test_internet_scout_health_returns_production_checks(monkeypatch):
    async def fake_build_health(conn):
        return InternetScoutHealthResponse(
            status="ok",
            checks={
                "database": InternetScoutHealthCheck(
                    ok=True,
                    status="ok",
                    detail="present",
                )
            },
            retention=InternetScoutRetentionReport(
                evidence_retention_days=90,
                screenshot_retention_days=30,
                generated_at=datetime(2026, 6, 6, tzinfo=UTC),
            ),
            checked_at=datetime(2026, 6, 6, tzinfo=UTC),
        )

    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "build_beacon_health", fake_build_health)

    response = await internet_scout.internet_scout_health(
        _request(scopes=["internet_scout.read"]),
        _user_id="ken",
    )

    assert response.status == "ok"
    assert response.checks["database"].ok is True
    assert response.retention.mode == "report_only"


@pytest.mark.asyncio
async def test_internet_scout_retention_report_is_report_only(monkeypatch):
    async def fake_retention_report(conn):
        return InternetScoutRetentionReport(
            evidence_retention_days=90,
            screenshot_retention_days=30,
            old_request_count=7,
        )

    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "build_retention_report", fake_retention_report)

    response = await internet_scout.internet_scout_retention_report(
        _request(scopes=["internet_scout.read"]),
        _user_id="ken",
    )

    assert response.mode == "report_only"
    assert response.old_request_count == 7


@pytest.mark.asyncio
async def test_internet_scout_retention_delete_requires_admin(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_retention_delete_expired(
            InternetScoutRetentionDeleteRequest(
                confirm="delete_expired_beacon_evidence"
            ),
            _request(scopes=["internet_scout.read"]),
            user_id="ken",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_internet_scout_retention_delete_uses_reviewed_service(monkeypatch):
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source: str, audit_actor: str):
        captured["source"] = source
        captured["audit_actor"] = audit_actor
        yield object()

    async def fake_delete_expired_evidence(conn, request):
        return InternetScoutRetentionDeleteResponse(
            mode="dry_run",
            enabled=True,
            dry_run=True,
            evidence_retention_days=90,
            screenshot_retention_days=30,
            candidate_request_count=2,
        )

    monkeypatch.setattr(
        internet_scout,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )
    monkeypatch.setattr(
        internet_scout,
        "delete_expired_evidence",
        fake_delete_expired_evidence,
    )

    response = await internet_scout.internet_scout_retention_delete_expired(
        InternetScoutRetentionDeleteRequest(confirm="delete_expired_beacon_evidence"),
        _request(scopes=["admin"]),
        user_id="ken",
    )

    assert response.mode == "dry_run"
    assert response.candidate_request_count == 2
    assert captured == {
        "source": "http",
        "audit_actor": "beacon_retention_delete:ken",
    }


@pytest.mark.asyncio
async def test_internet_scout_loads_stored_evidence(monkeypatch):
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)

    response = await internet_scout.internet_scout_request(
        FakeRepo.request_id,
        _request(scopes=["internet_scout.read"]),
        _user_id="ken",
    )

    assert response.request_id == FakeRepo.request_id
    assert response.evidence.sources[0].url == "https://public.example.test/report"


@pytest.mark.asyncio
async def test_internet_scout_local_llm_tool_returns_citation_envelope(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(internet_scout, "InternetScoutExecutor", lambda: FakeExecutor())

    response = await internet_scout.internet_scout_local_llm_tool(
        InternetScoutRequest(query="beacon"),
        _request(scopes=["internet_scout.research"]),
        _user_id="ken",
    )

    assert response.request_id == FakeRepo.request_id
    assert response.raw_web_content_is_untrusted is True
    assert response.citations[0].source_url == "https://public.example.test/report"
    assert "Beacon source." in response.answer_context
    assert FakeRepo.stored


@pytest.mark.asyncio
async def test_internet_scout_agent_run_returns_production_envelope(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(internet_scout, "InternetScoutExecutor", lambda: FakeExecutor())

    response = await internet_scout.internet_scout_agent_run(
        InternetScoutRequest(query="beacon"),
        _request(scopes=["internet_scout.research"]),
        _user_id="ken",
    )

    assert response.status == "completed"
    assert response.selected_tool == InternetTool.SEARCH
    assert response.request_id == FakeRepo.request_id
    assert response.confidence == "medium"
    assert response.raw_web_content_is_untrusted is True
    assert response.synthesis.required_behavior == "answer_with_limitations"
    assert response.memory_boundary.automatic_memory_write_allowed is False
    assert response.memory_boundary.promotion_review_required is True
    assert response.research_report.answerability == "limited"
    assert response.research_report.cited_source_count == 1
    assert response.citations[0].source_url == "https://public.example.test/report"
    assert "untrusted data" in response.untrusted_warnings[0]
    assert FakeRepo.stored


@pytest.mark.asyncio
async def test_internet_scout_agent_run_returns_browser_approval_required(
    monkeypatch,
):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)

    response = await internet_scout.internet_scout_agent_run(
        InternetScoutRequest(
            query="open the public page",
            urls=["https://public.example.test/start"],
            needs_interaction=True,
        ),
        _request(scopes=["internet_scout.research"]),
        _user_id="ken",
    )

    assert response.status == "approval_required"
    assert response.selected_tool == InternetTool.BROWSER_USE
    assert response.approval_required is True
    assert response.request_id == FakeRepo.request_id
    assert FakeRepo.created[0]["decision"].requires_approval is True
    assert any(event.get("event_type") == "policy" for event in FakeRepo.events)
    assert FakeRepo.stored == []


@pytest.mark.asyncio
async def test_internet_scout_consumer_local_llm_tool_enforces_consumer_policy(
    monkeypatch,
):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(internet_scout, "InternetScoutExecutor", lambda: FakeExecutor())

    response = await internet_scout.internet_scout_consumer_local_llm_tool(
        "family",
        InternetScoutConsumerRequest(query="school calendar source"),
        _request(scopes=["internet_scout.consumer.family"]),
        _user_id="ken",
    )

    created_request = FakeRepo.created[0]["request"]
    assert created_request.requester == "family"
    assert created_request.sensitivity == "minor"
    assert response.citations[0].citation_text == "Beacon source."


@pytest.mark.asyncio
async def test_internet_scout_consumer_local_llm_tool_blocks_disallowed_tool():
    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_consumer_local_llm_tool(
            "financial",
            InternetScoutConsumerRequest(
                urls=["https://public.example.test/markets"],
                max_pages=2,
            ),
            _request(scopes=["internet_scout.consumer.financial"]),
            _user_id="ken",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "consumer_tool_not_allowed"


@pytest.mark.asyncio
async def test_internet_scout_browser_approval_request_queues_only(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    queue_id = uuid4()
    enqueue_calls: list[dict[str, object]] = []

    async def fake_enqueue(conn, **kwargs):
        enqueue_calls.append(kwargs)
        return queue_id

    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(internet_scout, "enqueue_browser_task_approval", fake_enqueue)

    response = await internet_scout.internet_scout_browser_approval_request(
        InternetScoutRequest(
            query="open a public page and click through pagination",
            needs_interaction=True,
        ),
        _request(scopes=["internet_scout.research"]),
        _user_id="ken",
    )

    assert response.request_id == FakeRepo.request_id
    assert response.approval_queue_id == queue_id
    assert response.approval_status == "pending"
    assert response.preview.kind == "beacon_browser_use"
    assert response.preview.raw_task_text_included is False
    assert response.preview.raw_web_content_is_untrusted is True
    assert response.preview.has_query is True
    assert len(response.preview.approval_hash_prefix) == 12
    assert response.plan.decision.tool == InternetTool.BROWSER_USE
    assert response.plan.decision.requires_approval is True
    assert FakeRepo.created[0]["decision"].allowed is False
    assert enqueue_calls[0]["actor_sub"] == "ken"
    approval_event = next(
        event
        for event in FakeRepo.events
        if event.get("event_type") == "approval_request"
    )
    assert approval_event["status"] == "queued"
    assert approval_event["metadata"]["approval_hash_prefix"] == (
        response.preview.approval_hash_prefix
    )
    assert approval_event["metadata"]["browser_action_preview"]["url_count"] == 0
    assert FakeRepo.stored == []


@pytest.mark.asyncio
async def test_internet_scout_create_memory_promotions_from_stored_evidence(
    monkeypatch,
):
    FakeRepo.created = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    target_user_id = uuid4()

    response = await internet_scout.internet_scout_create_memory_promotions(
        FakeRepo.request_id,
        InternetScoutMemoryPromotionCreateRequest(
            target_user_id=target_user_id,
            candidates=[
                InternetScoutMemoryPromotionCandidate(
                    claim_index=0,
                    proposed_fact="Beacon has a reviewed fact.",
                    category="project",
                )
            ],
        ),
        _request(scopes=["internet_scout.memory_promote"]),
        _user_id="ken",
    )

    assert response.promotions[0].target_user_id == target_user_id
    assert response.promotions[0].status == "pending_review"
    assert FakeRepo.created[0]["memory_promotions"]["requested_by"] == "ken"


@pytest.mark.asyncio
async def test_internet_scout_review_memory_promotion_approves(monkeypatch):
    FakeRepo.events = []
    promotion_id = uuid4()
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)

    response = await internet_scout.internet_scout_review_memory_promotion(
        promotion_id,
        InternetScoutMemoryPromotionReviewRequest(decision="approve"),
        _request(scopes=["internet_scout.memory_promote"]),
        _user_id="ken",
    )

    assert response.promotion.id == promotion_id
    assert response.promotion.status == "promoted"
    assert FakeRepo.events[0]["memory_review"]["reviewer"] == "ken"


@pytest.mark.asyncio
async def test_internet_scout_browser_run_approved_executes_and_consumes(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    approval_queue_id = uuid4()
    approval_calls: list[dict[str, object]] = []
    consume_calls: list[object] = []

    async def fake_require_approved(conn, **kwargs):
        approval_calls.append(kwargs)

    async def fake_consume(conn, **kwargs):
        consume_calls.append(kwargs["approval_queue_id"])

    class FakeBrowserRunner:
        async def execute(self, **kwargs):
            observation = BrowserRunObservation(
                url="https://public.example.test/result",
                host="public.example.test",
                title="Result",
                visible_text="Browser observed text.",
                screenshot_ref="sha256:" + "3" * 64,
                content_hash=content_hash("Browser observed text."),
            )
            source = build_source_reference(
                url=observation.url,
                title=observation.title,
                content=observation.visible_text,
            )
            packet = InternetEvidencePacket(
                request=kwargs["request"],
                sources=[source],
                claims=[
                    EvidenceClaim(
                        claim=observation.visible_text,
                        source_url=source.url,
                        citation_text=observation.visible_text,
                        confidence="medium",
                    )
                ],
            )
            return InternetScoutBrowserRunResponse(
                request_id=kwargs["request_id"],
                approval_queue_id=kwargs["approval_queue_id"],
                status="completed",
                plan=kwargs["plan"],
                sandbox=BrowserSandboxPolicy(
                    allowed_hosts=["public.example.test"],
                    max_steps=kwargs["max_steps"],
                ),
                evidence=packet,
                observations=[observation],
                screenshots_review_required=True,
                blocked_reasons=[],
            )

    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(
        internet_scout, "require_approved_browser_task", fake_require_approved
    )
    monkeypatch.setattr(internet_scout, "consume_browser_task_approval", fake_consume)
    monkeypatch.setattr(
        internet_scout,
        "build_browser_task_runner_from_env",
        lambda: FakeBrowserRunner(),
    )

    response = await internet_scout.internet_scout_browser_run_approved(
        InternetScoutBrowserRunRequest(
            approval_queue_id=approval_queue_id,
            browser_request=InternetScoutRequest(
                query="open pricing",
                urls=["https://public.example.test/start"],
            ),
            max_steps=4,
        ),
        _request(scopes=["internet_scout.research"]),
        _user_id="ken",
    )

    assert response.status == "completed"
    assert response.evidence.claims[0].citation_text == "Browser observed text."
    assert approval_calls[0]["approval_queue_id"] == approval_queue_id
    assert consume_calls == [approval_queue_id]
    assert FakeRepo.created[0]["status_override"] == "running"
    assert any(event.get("status") == "succeeded" for event in FakeRepo.events)
    assert len(FakeRepo.stored) == 1


@pytest.mark.asyncio
async def test_internet_scout_browser_approval_request_rejects_empty_task():
    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_browser_approval_request(
            InternetScoutRequest(needs_interaction=True),
            _request(scopes=["internet_scout.research"]),
            _user_id="ken",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "browser_use_task_required"


def test_internet_scout_routes_are_classified():
    assert classify_route("GET", "/v1/internet-scout/health") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/internet-scout/retention/report") == [
        "read",
        "security_read",
    ]
    assert classify_route("POST", "/v1/internet-scout/retention/delete-expired") == [
        "write",
        "security_write",
        "destructive",
    ]
    assert classify_route("POST", "/v1/internet-scout/research") == [
        "write",
        "external_call",
        "cost_incurring",
    ]
    assert classify_route("POST", "/v1/internet-scout/agent/run") == [
        "write",
        "external_call",
        "cost_incurring",
    ]
    assert classify_route("POST", "/v1/internet-scout/local-llm/tool") == [
        "write",
        "external_call",
        "cost_incurring",
    ]
    assert classify_route(
        "POST",
        "/v1/internet-scout/consumers/family/local-llm/tool",
    ) == [
        "write",
        "external_call",
        "cost_incurring",
    ]
    assert classify_route(
        "POST",
        "/v1/internet-scout/browser-task/approval-request",
    ) == [
        "write",
        "security_write",
    ]
    assert classify_route(
        "POST",
        "/v1/internet-scout/requests/123/memory-promotions",
    ) == [
        "write",
        "security_write",
    ]
    assert classify_route(
        "POST",
        "/v1/internet-scout/memory-promotions/123/review",
    ) == [
        "write",
        "security_write",
    ]
    assert classify_route(
        "POST",
        "/v1/internet-scout/browser-task/run-approved",
    ) == [
        "write",
        "security_write",
        "external_call",
    ]
    assert classify_route("GET", "/v1/internet-scout/requests/123") == [
        "read",
        "security_read",
    ]
