from __future__ import annotations

import json
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
    BrowserActionAuditEvent,
    BrowserRunObservation,
    BrowserSandboxPolicy,
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutBrowserRunRequest,
    InternetScoutBrowserRunResponse,
    InternetScoutConsumerRequest,
    InternetScoutCrawlerRenderRunRequest,
    InternetScoutCrawlerScrapeRequest,
    InternetScoutCrawlerScrapeResponse,
    InternetScoutHealthCheck,
    InternetScoutHealthResponse,
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


def _decode_sse_event(chunk: str) -> dict[str, object]:
    lines = chunk.strip().splitlines()
    event = next(
        line.split(":", 1)[1].strip() for line in lines if line.startswith("event:")
    )
    data = next(
        line.split(":", 1)[1].strip() for line in lines if line.startswith("data:")
    )
    return {"event": event, "data": json.loads(data)}


def test_internet_scout_stream_failure_detail_is_sanitized():
    detail = internet_scout._stream_failure_detail(
        RuntimeError("provider failed with secret-token-value")
    )

    assert detail == {
        "detail": "Beacon request failed before completion.",
        "request_id": None,
    }


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
        if "tool" in kwargs:
            assert kwargs["tool"] in {
                "search",
                "fetch",
                "extract",
                "crawl",
                "browser_use",
            }
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

    async def web_cache_extract_response(self, **kwargs):
        return None

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
    async def execute(self, body, *, plan=None):
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


class FakeCrawler:
    async def scrape(self, body, request_id, scout_request, *, cache_lookup=None):
        source = build_source_reference(
            url="https://public.example.test/report",
            content="Crawler source.",
        )
        packet = InternetEvidencePacket(
            request=scout_request,
            sources=[source],
            claims=[
                EvidenceClaim(
                    claim="Crawler source.",
                    source_url=source.url,
                    citation_text="Crawler source.",
                    confidence="medium",
                )
            ],
        )
        return (
            InternetScoutCrawlerScrapeResponse(
                request_id=request_id,
                canonical_url=source.url,
                host=source.host,
                fetched_at=source.fetched_at,
                text="Crawler source.",
                links=["https://public.example.test/docs"],
                content_hash=source.content_hash,
            ),
            packet,
            {
                "operation": "scrape",
                "cache_hit": False,
                "source_count": 1,
                "claim_count": 1,
                "same_host_required": True,
                "forms_allowed": False,
                "credential_entry_allowed": False,
            },
        )


class FakeFailingCrawler:
    async def scrape(self, body, request_id, scout_request, *, cache_lookup=None):
        raise RuntimeError("gateway failed with secret-token-value")


@asynccontextmanager
async def fake_rls_connection(request):
    yield object()


class FakeHistoryConn:
    instances: list["FakeHistoryConn"] = []
    approval_queue_id = uuid4()
    browser_request_id = uuid4()
    approval_request_id = uuid4()

    def __init__(self) -> None:
        self.fetch_calls: list[tuple] = []

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, *args))
        return [
            {
                "request_id": self.browser_request_id,
                "event_type": "browser_action",
                "status": "succeeded",
                "created_at": datetime(2026, 6, 18, 12, 3, tzinfo=UTC),
                "selected_tool": "browser_use",
                "request_status": "succeeded",
                "risk_tier": "T5",
                "approval_queue_id": str(self.approval_queue_id),
                "approval_hash_prefix": "abc123abc123",
                "observation_count": 0,
                "screenshot_count": 0,
                "action_audit_count": 0,
                "action": "navigate",
                "host": "public.example.test",
                "blocked_reason": None,
                "elapsed_ms": 12,
            },
            {
                "request_id": self.browser_request_id,
                "event_type": "browser_run",
                "status": "succeeded",
                "created_at": datetime(2026, 6, 18, 12, 2, tzinfo=UTC),
                "selected_tool": "browser_use",
                "request_status": "succeeded",
                "risk_tier": "T5",
                "approval_queue_id": str(self.approval_queue_id),
                "approval_hash_prefix": None,
                "observation_count": 1,
                "screenshot_count": 1,
                "action_audit_count": 2,
                "action": None,
                "host": None,
                "blocked_reason": None,
                "elapsed_ms": None,
            },
            {
                "request_id": self.approval_request_id,
                "event_type": "approval_request",
                "status": "queued",
                "created_at": datetime(2026, 6, 18, 12, 1, tzinfo=UTC),
                "selected_tool": "browser_use",
                "request_status": "blocked",
                "risk_tier": "T5",
                "approval_queue_id": str(self.approval_queue_id),
                "approval_hash_prefix": "abc123abc123",
                "observation_count": 0,
                "screenshot_count": 0,
                "action_audit_count": 0,
                "action": None,
                "host": None,
                "blocked_reason": None,
                "elapsed_ms": None,
            },
        ]


class FakeRequestHistoryConn:
    instances: list["FakeRequestHistoryConn"] = []
    request_id = uuid4()

    def __init__(self) -> None:
        self.fetch_calls: list[tuple] = []

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, *args))
        return [
            {
                "request_id": self.request_id,
                "requester": "alpha_ui.beacon_answer_engine.deep_research",
                "selected_tool": "search",
                "sensitivity": "normal",
                "status": "succeeded",
                "risk_tier": "T1",
                "created_at": datetime(2026, 6, 18, 13, 5, tzinfo=UTC),
                "updated_at": datetime(2026, 6, 18, 13, 6, tzinfo=UTC),
                "has_query": True,
                "url_count": 0,
                "max_pages": 4,
                "max_depth": 0,
                "needs_interaction": False,
                "source_count": 3,
                "claim_count": 5,
                "event_count": 2,
                "source_hosts": ["docs.example.test", "status.example.test"],
                "latest_event_type": "gateway_call",
                "latest_event_status": "succeeded",
                "latest_event_metadata": {},
            },
            {
                "request_id": uuid4(),
                "requester": "alpha_ui.beacon_crawler.crawl",
                "selected_tool": "crawl",
                "sensitivity": "normal",
                "status": "succeeded",
                "risk_tier": "T1",
                "created_at": datetime(2026, 6, 18, 12, 5, tzinfo=UTC),
                "updated_at": datetime(2026, 6, 18, 12, 5, tzinfo=UTC),
                "has_query": False,
                "url_count": 1,
                "max_pages": 3,
                "max_depth": 1,
                "needs_interaction": False,
                "source_count": 2,
                "claim_count": 2,
                "event_count": 2,
                "source_hosts": ["public.example.test"],
                "latest_event_type": "crawler_crawl",
                "latest_event_status": "succeeded",
                "latest_event_metadata": {
                    "operation": "crawl",
                    "cache_hit": False,
                    "page_count": 2,
                    "link_count": 4,
                    "blocked_reasons": ["robots_blocked"],
                    "error_type": "ignored",
                },
            },
        ]


@asynccontextmanager
async def fake_history_connection(request):
    conn = FakeHistoryConn()
    FakeHistoryConn.instances.append(conn)
    yield conn


@asynccontextmanager
async def fake_request_history_connection(request):
    conn = FakeRequestHistoryConn()
    FakeRequestHistoryConn.instances.append(conn)
    yield conn


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
async def test_internet_scout_crawler_scrape_stores_cacheable_audit(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(internet_scout, "InternetScoutCrawler", lambda: FakeCrawler())

    response = await internet_scout.internet_scout_crawler_scrape(
        InternetScoutCrawlerScrapeRequest(url="https://public.example.test/report"),
        _request(scopes=["internet_scout.research"]),
        _user_id="ken",
    )

    assert response.request_id == FakeRepo.request_id
    assert response.host == "public.example.test"
    assert response.raw_web_content_is_untrusted is True
    assert FakeRepo.created[0]["request"].requester == "alpha_ui.beacon_crawler.scrape"
    assert FakeRepo.created[0]["decision"].tool == InternetTool.EXTRACT
    assert FakeRepo.stored[0]["packet"].claims[0].citation_text == "Crawler source."
    crawler_event = next(
        event
        for event in FakeRepo.events
        if event.get("event_type") == "crawler_scrape"
        and event.get("status") == "succeeded"
    )
    assert crawler_event["tool"] == "extract"
    assert crawler_event["metadata"]["cache_hit"] is False
    assert crawler_event["metadata"]["credential_entry_allowed"] is False


@pytest.mark.asyncio
async def test_internet_scout_crawler_scrape_blocks_unsafe_url(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)

    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_crawler_scrape(
            InternetScoutCrawlerScrapeRequest(url="http://localhost/private"),
            _request(scopes=["internet_scout.research"]),
            _user_id="ken",
        )

    assert exc.value.status_code == 403
    blocked_event = next(
        event for event in FakeRepo.events if event.get("status") == "blocked"
    )
    assert blocked_event["event_type"] == "crawler_scrape"
    assert blocked_event["tool"] == "extract"
    assert "blocked_internal_host" in blocked_event["metadata"]["blocked_reasons"]
    assert FakeRepo.stored == []


@pytest.mark.asyncio
async def test_internet_scout_crawler_render_scrape_queues_browser_approval(
    monkeypatch,
):
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

    response = (
        await internet_scout.internet_scout_crawler_scrape_browser_approval_request(
            InternetScoutCrawlerScrapeRequest(
                url="https://public.example.test/report",
                query="render this page",
            ),
            _request(scopes=["internet_scout.research"]),
            _user_id="ken",
        )
    )

    assert response.approval_queue_id == queue_id
    assert response.plan.decision.tool == InternetTool.BROWSER_USE
    assert response.plan.decision.requires_approval is True
    assert response.preview.allowed_hosts == ["public.example.test"]
    assert FakeRepo.created[0]["request"].requester == (
        "alpha_ui.beacon_crawler.render_scrape"
    )
    assert FakeRepo.created[0]["request"].max_pages == 1
    assert FakeRepo.created[0]["request"].max_depth == 0
    assert FakeRepo.created[0]["request"].browser_clicks == []
    assert enqueue_calls[0]["actor_sub"] == "ken"
    approval_event = next(
        event
        for event in FakeRepo.events
        if event.get("event_type") == "approval_request"
    )
    assert approval_event["tool"] == "browser_use"
    assert approval_event["status"] == "queued"
    assert approval_event["metadata"]["source"] == "crawler_render_scrape"
    assert approval_event["metadata"]["require_screenshot"] is True
    assert FakeRepo.stored == []


@pytest.mark.asyncio
async def test_internet_scout_crawler_render_scrape_blocks_unsafe_url(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)

    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_crawler_scrape_browser_approval_request(
            InternetScoutCrawlerScrapeRequest(url="http://localhost/private"),
            _request(scopes=["internet_scout.research"]),
            _user_id="ken",
        )

    assert exc.value.status_code == 403
    assert "blocked_internal_host" in exc.value.detail["decision"]["blocked_reasons"]
    assert FakeRepo.created == []
    assert FakeRepo.events == []
    assert FakeRepo.stored == []


@pytest.mark.asyncio
async def test_internet_scout_crawler_render_scrape_run_returns_crawler_shape(
    monkeypatch,
):
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
            assert kwargs["approval_queue_id"] == approval_queue_id
            assert (
                kwargs["request"].requester == "alpha_ui.beacon_crawler.render_scrape"
            )
            assert kwargs["request"].browser_clicks == []
            assert kwargs["require_screenshot"] is True
            await kwargs["audit_action"](
                BrowserActionAuditEvent(
                    sequence=1,
                    action="observe",
                    status="succeeded",
                    host="public.example.test",
                    url_hash="sha256:" + "4" * 64,
                    screenshot_ref="sha256:" + "3" * 64,
                    content_hash=content_hash("Rendered text."),
                )
            )
            observation = BrowserRunObservation(
                url="https://public.example.test/rendered",
                host="public.example.test",
                title="Rendered",
                visible_text="Rendered text.",
                screenshot_ref="sha256:" + "3" * 64,
                content_hash=content_hash("Rendered text."),
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
                action_audit=[
                    BrowserActionAuditEvent(
                        sequence=1,
                        action="observe",
                        status="succeeded",
                        host="public.example.test",
                        url_hash="sha256:" + "4" * 64,
                        screenshot_ref="sha256:" + "3" * 64,
                        content_hash=content_hash("Rendered text."),
                    )
                ],
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

    response = await internet_scout.internet_scout_crawler_scrape_browser_run_approved(
        InternetScoutCrawlerRenderRunRequest(
            approval_queue_id=approval_queue_id,
            scrape=InternetScoutCrawlerScrapeRequest(
                url="https://public.example.test/report",
                query="render this page",
            ),
            max_steps=4,
        ),
        _request(scopes=["internet_scout.research"]),
        _user_id="ken",
    )

    assert response.request_id == FakeRepo.request_id
    assert response.approval_queue_id == approval_queue_id
    assert response.canonical_url == "https://public.example.test/rendered"
    assert response.host == "public.example.test"
    assert response.title == "Rendered"
    assert response.text == "Rendered text."
    assert response.screenshot_ref == "sha256:" + "3" * 64
    assert (
        response.evidence_path == f"/v1/internet-scout/requests/{FakeRepo.request_id}"
    )
    assert response.audit_path == (
        f"/v1/internet-scout/browser-task/history?q={approval_queue_id}"
    )
    assert response.action_audit_count == 1
    assert response.evidence_source_count == 1
    assert approval_calls[0]["approval_queue_id"] == approval_queue_id
    assert consume_calls == [approval_queue_id]
    assert FakeRepo.created[0]["status_override"] == "running"
    assert len(FakeRepo.stored) == 1
    assert any(
        event.get("event_type") == "browser_run" and event.get("status") == "succeeded"
        for event in FakeRepo.events
    )


@pytest.mark.asyncio
async def test_internet_scout_crawler_render_scrape_run_blocks_unsafe_url(
    monkeypatch,
):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    approval_calls: list[dict[str, object]] = []

    async def fake_require_approved(conn, **kwargs):
        approval_calls.append(kwargs)

    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(
        internet_scout, "require_approved_browser_task", fake_require_approved
    )

    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_crawler_scrape_browser_run_approved(
            InternetScoutCrawlerRenderRunRequest(
                approval_queue_id=uuid4(),
                scrape=InternetScoutCrawlerScrapeRequest(
                    url="http://localhost/private",
                ),
            ),
            _request(scopes=["internet_scout.research"]),
            _user_id="ken",
        )

    assert exc.value.status_code == 403
    assert "blocked_internal_host" in exc.value.detail["decision"]["blocked_reasons"]
    assert approval_calls == []
    assert FakeRepo.created == []
    assert FakeRepo.events == []
    assert FakeRepo.stored == []


@pytest.mark.asyncio
async def test_internet_scout_crawler_failure_audit_is_sanitized(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(
        internet_scout,
        "InternetScoutCrawler",
        lambda: FakeFailingCrawler(),
    )

    with pytest.raises(RuntimeError):
        await internet_scout.internet_scout_crawler_scrape(
            InternetScoutCrawlerScrapeRequest(url="https://public.example.test/report"),
            _request(scopes=["internet_scout.research"]),
            _user_id="ken",
        )

    failed_event = next(
        event for event in FakeRepo.events if event.get("status") == "failed"
    )
    assert failed_event["error_text"] == "Beacon crawler request failed."
    assert failed_event["metadata"]["error_type"] == "RuntimeError"
    assert "secret-token-value" not in str(FakeRepo.events)
    assert "secret-token-value" not in str(FakeRepo.created)


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
async def test_internet_scout_browser_history_returns_recent_audit_events(
    monkeypatch,
):
    FakeHistoryConn.instances = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_history_connection)

    response = await internet_scout.internet_scout_browser_history(
        _request(scopes=["internet_scout.read"]),
        _user_id="ken",
        limit=99,
    )

    query, event_type, search, limit, offset = FakeHistoryConn.instances[0].fetch_calls[
        0
    ]
    assert response.count == 3
    assert response.limit == 50
    assert response.offset == 0
    assert response.has_more is False
    assert event_type is None
    assert search is None
    assert limit == 51
    assert offset == 0
    assert "alpha_internet_tool_events" in query
    assert response.history[0].event_type == "browser_action"
    assert response.history[0].action == "navigate"
    assert response.history[0].host == "public.example.test"
    assert response.history[0].elapsed_ms == 12
    assert response.history[0].approval_queue_id == FakeHistoryConn.approval_queue_id
    assert response.history[1].event_type == "browser_run"
    assert response.history[1].observation_count == 1
    assert response.history[1].screenshot_count == 1
    assert response.history[1].action_audit_count == 2
    assert response.history[2].event_type == "approval_request"
    assert response.history[2].approval_hash_prefix == "abc123abc123"


@pytest.mark.asyncio
async def test_internet_scout_browser_history_reports_more_pages(monkeypatch):
    FakeHistoryConn.instances = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_history_connection)

    response = await internet_scout.internet_scout_browser_history(
        _request(scopes=["internet_scout.read"]),
        _user_id="ken",
        limit=2,
    )

    assert response.count == 2
    assert response.has_more is True
    assert [item.event_type for item in response.history] == [
        "browser_action",
        "browser_run",
    ]


@pytest.mark.asyncio
async def test_internet_scout_browser_history_passes_filters_to_query(monkeypatch):
    FakeHistoryConn.instances = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_history_connection)

    response = await internet_scout.internet_scout_browser_history(
        _request(scopes=["internet_scout.read"]),
        _user_id="ken",
        limit=12,
        offset=12,
        event_type="browser_action",
        q="Example.TEST",
    )

    query, event_type, search, limit, offset = FakeHistoryConn.instances[0].fetch_calls[
        0
    ]
    assert response.offset == 12
    assert event_type == "browser_action"
    assert search == "%example.test%"
    assert limit == 13
    assert offset == 12
    assert "$1::text IS NULL OR event.event_type = $1" in query
    assert "LIKE $2" in query


@pytest.mark.asyncio
async def test_internet_scout_browser_history_rejects_unknown_event_type(monkeypatch):
    FakeHistoryConn.instances = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_history_connection)

    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_browser_history(
            _request(scopes=["internet_scout.read"]),
            _user_id="ken",
            event_type="not_browser_history",
        )

    assert exc.value.status_code == 400
    assert FakeHistoryConn.instances == []


@pytest.mark.asyncio
async def test_internet_scout_browser_history_requires_read_scope():
    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_browser_history(
            _request(),
            _user_id="ken",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_internet_scout_request_history_returns_saved_requests(monkeypatch):
    FakeRequestHistoryConn.instances = []
    monkeypatch.setattr(
        internet_scout, "rls_connection", fake_request_history_connection
    )

    response = await internet_scout.internet_scout_request_history(
        _request(scopes=["internet_scout.read"]),
        _user_id="ken",
        limit=99,
    )

    query, status, search, limit, offset = FakeRequestHistoryConn.instances[
        0
    ].fetch_calls[0]
    assert response.count == 2
    assert response.limit == 50
    assert response.offset == 0
    assert response.has_more is False
    assert status is None
    assert search is None
    assert limit == 51
    assert offset == 0
    assert "alpha_internet_requests" in query
    assert "alpha_internet_sources" in query
    assert "alpha_internet_evidence" in query
    assert response.history[0].request_id == FakeRequestHistoryConn.request_id
    assert response.history[0].selected_tool == "search"
    assert response.history[0].source_count == 3
    assert response.history[0].claim_count == 5
    assert response.history[0].latest_event_type == "gateway_call"
    assert response.history[1].selected_tool == "crawl"
    assert response.history[1].crawler_operation == "crawl"
    assert response.history[1].crawler_cache_hit is False
    assert response.history[1].crawler_page_count == 2
    assert response.history[1].crawler_link_count == 4
    assert response.history[1].crawler_blocked_reasons == ["robots_blocked"]
    assert response.history[1].crawler_error_type == "ignored"


@pytest.mark.asyncio
async def test_internet_scout_request_history_passes_filters_to_query(monkeypatch):
    FakeRequestHistoryConn.instances = []
    monkeypatch.setattr(
        internet_scout, "rls_connection", fake_request_history_connection
    )

    response = await internet_scout.internet_scout_request_history(
        _request(scopes=["internet_scout.read"]),
        _user_id="ken",
        limit=12,
        offset=12,
        status="succeeded",
        q="Docs.EXAMPLE",
    )

    query, status, search, limit, offset = FakeRequestHistoryConn.instances[
        0
    ].fetch_calls[0]
    assert response.offset == 12
    assert status == "succeeded"
    assert search == "%docs.example%"
    assert limit == 13
    assert offset == 12
    assert "$1::text IS NULL OR request.status = $1" in query
    assert "LIKE $2" in query


@pytest.mark.asyncio
async def test_internet_scout_request_history_rejects_unknown_status(monkeypatch):
    FakeRequestHistoryConn.instances = []
    monkeypatch.setattr(
        internet_scout, "rls_connection", fake_request_history_connection
    )

    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_request_history(
            _request(scopes=["internet_scout.read"]),
            _user_id="ken",
            status="not_real",
        )

    assert exc.value.status_code == 400
    assert FakeRequestHistoryConn.instances == []


@pytest.mark.asyncio
async def test_internet_scout_request_history_requires_read_scope():
    with pytest.raises(HTTPException) as exc:
        await internet_scout.internet_scout_request_history(
            _request(),
            _user_id="ken",
        )

    assert exc.value.status_code == 403


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
async def test_internet_scout_local_llm_stream_returns_steps_and_bundle(monkeypatch):
    FakeRepo.created = []
    FakeRepo.events = []
    FakeRepo.stored = []
    monkeypatch.setattr(internet_scout, "rls_connection", fake_rls_connection)
    monkeypatch.setattr(internet_scout, "InternetScoutRepository", FakeRepo)
    monkeypatch.setattr(internet_scout, "InternetScoutExecutor", lambda: FakeExecutor())

    chunks = [
        chunk
        async for chunk in internet_scout._stream_local_llm_tool(
            InternetScoutRequest(query="beacon"),
            _request(scopes=["internet_scout.research"]),
        )
    ]
    events = [_decode_sse_event(chunk) for chunk in chunks]

    assert [event["event"] for event in events] == [
        "step",
        "step",
        "step",
        "completed",
    ]
    assert events[0]["data"]["stage"] == "planned"
    assert events[1]["data"]["stage"] == "executing"
    assert events[2]["data"]["stage"] == "synthesizing"
    assert events[3]["data"]["evidence_bundle"]["raw_web_content_included"] is False
    assert (
        events[3]["data"]["evidence_bundle"]["citations"][0]["source_url"]
        == "https://public.example.test/report"
    )


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
            await kwargs["audit_action"](
                BrowserActionAuditEvent(
                    sequence=1,
                    action="navigate",
                    status="started",
                    host="public.example.test",
                    url_hash="sha256:" + "4" * 64,
                )
            )
            await kwargs["audit_action"](
                BrowserActionAuditEvent(
                    sequence=1,
                    action="navigate",
                    status="succeeded",
                    host="public.example.test",
                    url_hash="sha256:" + "4" * 64,
                    elapsed_ms=12,
                )
            )
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
                action_audit=[
                    BrowserActionAuditEvent(
                        sequence=1,
                        action="navigate",
                        status="started",
                        host="public.example.test",
                        url_hash="sha256:" + "4" * 64,
                    ),
                    BrowserActionAuditEvent(
                        sequence=1,
                        action="navigate",
                        status="succeeded",
                        host="public.example.test",
                        url_hash="sha256:" + "4" * 64,
                        elapsed_ms=12,
                    ),
                ],
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
    action_events = [
        event
        for event in FakeRepo.events
        if event.get("event_type") == "browser_action"
    ]
    assert [event["status"] for event in action_events] == ["started", "succeeded"]
    assert action_events[0]["metadata"]["raw_task_text_included"] is False
    assert action_events[0]["metadata"]["raw_web_content_included"] is False
    assert action_events[0]["metadata"]["credential_entry_allowed"] is False
    assert action_events[0]["metadata"]["forms_allowed"] is False
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
    assert classify_route("POST", "/v1/internet-scout/local-llm/tool/stream") == [
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
    for path in (
        "/v1/internet-scout/crawler/scrape",
        "/v1/internet-scout/crawler/map",
        "/v1/internet-scout/crawler/crawl",
        "/v1/internet-scout/crawler/extract",
    ):
        assert classify_route("POST", path) == ["write", "external_call"]
    assert classify_route(
        "POST",
        "/v1/internet-scout/browser-task/approval-request",
    ) == [
        "write",
        "security_write",
    ]
    assert classify_route(
        "POST",
        "/v1/internet-scout/crawler/scrape/browser-approval-request",
    ) == [
        "write",
        "security_write",
    ]
    assert classify_route(
        "POST",
        "/v1/internet-scout/crawler/scrape/browser-run-approved",
    ) == [
        "write",
        "security_write",
        "external_call",
    ]
    assert classify_route("GET", "/v1/internet-scout/browser-task/history") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/internet-scout/requests") == [
        "read",
        "security_read",
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
