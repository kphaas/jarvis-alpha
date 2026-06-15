from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from uuid import uuid4

import pytest

from brain.services.internet_scout import health as beacon_health
from brain.services.internet_scout.models import InternetScoutRetentionDeleteRequest
from brain.services.internet_scout.retention import (
    build_retention_report,
    delete_expired_evidence,
)


class FakeConn:
    def __init__(
        self,
        counts: dict[str, int] | None = None,
        recent_row: dict[str, int] | None = None,
        last_request_row: dict[str, object] | None = None,
        quality_row: dict[str, int] | None = None,
        suggestion_row: dict[str, int] | None = None,
        acceptance_row: dict[str, int] | None = None,
        quality_canary_row: dict[str, object] | None = None,
        expired_request_ids: list[object] | None = None,
        delete_counts: dict[str, int] | None = None,
    ) -> None:
        self.counts = counts or {}
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.expired_request_ids = expired_request_ids or []
        self.delete_counts = delete_counts or {}
        self.recent_row = recent_row or {
            "total": 3,
            "succeeded": 2,
            "failed": 0,
            "blocked": 1,
        }
        now = datetime.now(UTC)
        self.last_request_row = last_request_row or {
            "id": uuid4(),
            "requester": "production_smoke",
            "selected_tool": "search",
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
        }
        self.quality_row = quality_row or {
            "supported_source_quality": 2,
            "weak_source_quality": 1,
            "insufficient_source_quality": 1,
            "rejected_citation_count": 3,
            "official_source_count": 1,
            "prompt_injection_rejection_count": 1,
        }
        self.suggestion_row = suggestion_row or {
            "suggested": 5,
            "high_confidence": 3,
            "medium_confidence": 2,
        }
        self.acceptance_row = acceptance_row or {
            "accepted": 2,
            "accepted_matching_mode": 2,
            "accepted_after_confirmation": 2,
        }
        self.quality_canary_row = quality_canary_row or {
            "request_id": uuid4(),
            "status": "succeeded",
            "created_at": now,
            "metadata": {
                "suite": "beacon_search_quality",
                "suite_version": 2,
                "case_count": 33,
                "passed": 33,
                "failed": 0,
                "failure_names": [],
                "status": "passed",
            },
        }

    async def fetchval(self, query: str, *args):
        if "to_regclass" in query:
            return args[0]
        if "to_regprocedure" in query:
            return args[0]
        for table, count in self.counts.items():
            if f"public.{table}" in query:
                return count
        return 0

    async def fetch(self, query: str, *args):
        if "FROM public.alpha_internet_requests" in query:
            return [{"id": request_id} for request_id in self.expired_request_ids]
        return []

    async def fetchrow(self, query: str, *args):
        if "quality_canary" in query:
            return self.quality_canary_row
        if "chat_web_suggestion_acceptance" in query:
            return self.acceptance_row
        if "FROM public.chat_messages" in query:
            return self.suggestion_row
        if "chat_evidence_quality" in query:
            return self.quality_row
        if "ORDER BY created_at DESC" in query:
            return self.last_request_row
        return self.recent_row

    async def execute(self, query: str, *args):
        self.executed.append((query, args))
        for table, count in self.delete_counts.items():
            if f"public.{table}" in query:
                return f"DELETE {count}"
        return "SELECT 1"


class FakeGatewayClient:
    def __init__(self, *, usable_provider_count: int = 2) -> None:
        self.usable_provider_count = usable_provider_count

    async def health(self):
        return {
            "status": "ok" if self.usable_provider_count else "degraded",
            "provider_order": ["brave", "perplexity"],
            "configured_provider_count": 2,
            "usable_provider_count": self.usable_provider_count,
            "providers": [
                {
                    "provider": "brave",
                    "configured": True,
                    "circuit_open": False,
                }
            ],
        }


@pytest.mark.asyncio
async def test_retention_report_counts_old_rows_and_screenshots(
    monkeypatch,
    tmp_path,
):
    old_png = tmp_path / "old.png"
    old_png.write_bytes(b"old")
    new_png = tmp_path / "new.png"
    new_png.write_bytes(b"new")
    old_timestamp = (datetime.now(UTC) - timedelta(days=45)).timestamp()
    os.utime(old_png, (old_timestamp, old_timestamp))
    monkeypatch.setenv("BEACON_BROWSER_SCREENSHOT_DIR", str(tmp_path))
    monkeypatch.setenv("BEACON_EVIDENCE_RETENTION_DAYS", "30")
    monkeypatch.setenv("BEACON_BROWSER_SCREENSHOT_RETENTION_DAYS", "30")

    report = await build_retention_report(
        FakeConn(
            {
                "alpha_internet_requests": 4,
                "alpha_internet_sources": 5,
                "alpha_internet_evidence": 6,
                "alpha_internet_tool_events": 7,
                "alpha_internet_memory_promotions": 8,
            }
        )
    )

    assert report.mode == "report_only"
    assert report.evidence_retention_days == 30
    assert report.old_request_count == 4
    assert report.old_event_count == 7
    assert report.old_memory_promotion_count == 8
    assert report.screenshot_file_count == 1
    assert report.screenshot_bytes == 3


@pytest.mark.asyncio
async def test_retention_delete_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("BEACON_RETENTION_DELETE_ENABLED", raising=False)
    conn = FakeConn(expired_request_ids=[uuid4()])

    response = await delete_expired_evidence(
        conn,
        InternetScoutRetentionDeleteRequest(
            confirm="delete_expired_beacon_evidence",
            dry_run=False,
        ),
    )

    assert response.mode == "disabled"
    assert response.enabled is False
    assert response.dry_run is True
    assert response.candidate_request_count == 1
    assert response.deleted_request_count == 0
    assert conn.executed == []


@pytest.mark.asyncio
async def test_retention_delete_removes_expired_rows_when_enabled(monkeypatch):
    monkeypatch.setenv("BEACON_RETENTION_DELETE_ENABLED", "true")
    request_id = uuid4()
    conn = FakeConn(
        expired_request_ids=[request_id],
        delete_counts={
            "alpha_internet_memory_promotions": 1,
            "alpha_internet_evidence": 2,
            "alpha_internet_sources": 3,
            "alpha_internet_tool_events": 4,
            "alpha_internet_requests": 1,
        },
    )

    response = await delete_expired_evidence(
        conn,
        InternetScoutRetentionDeleteRequest(
            confirm="delete_expired_beacon_evidence",
            dry_run=False,
        ),
    )

    assert response.mode == "deleted"
    assert response.enabled is True
    assert response.dry_run is False
    assert response.deleted_memory_promotion_count == 1
    assert response.deleted_evidence_count == 2
    assert response.deleted_source_count == 3
    assert response.deleted_event_count == 4
    assert response.deleted_request_count == 1
    assert "app.beacon_retention_cleanup" in conn.executed[0][0]


@pytest.mark.asyncio
async def test_health_aggregates_gateway_browser_db_and_retention(monkeypatch):
    monkeypatch.setattr(
        beacon_health,
        "browser_runtime_health",
        lambda: {
            "ok": True,
            "runtime": "playwright",
            "runtime_enabled": True,
            "playwright_version_ok": True,
            "screenshot_dir_writable": True,
        },
    )

    response = await beacon_health.build_beacon_health(
        FakeConn(),
        gateway_client=FakeGatewayClient(),
    )

    assert response.status == "ok"
    assert response.checks["database"].ok is True
    assert response.checks["gateway"].metadata["usable_provider_count"] == 2
    assert response.checks["browser_runtime"].ok is True
    assert response.checks["recent_evidence"].metadata["blocked"] == 1
    source_quality = response.checks["recent_evidence"].metadata["source_quality"]
    assert source_quality == {
        "supported": 2,
        "weak": 1,
        "insufficient": 1,
        "rejected_citation_count": 3,
        "official_source_count": 1,
        "prompt_injection_rejection_count": 1,
    }
    web_suggestion = response.checks["recent_evidence"].metadata["web_suggestion"]
    assert web_suggestion == {
        "suggested": 5,
        "accepted": 2,
        "acceptance_rate_percent": 40,
        "high_confidence": 3,
        "medium_confidence": 2,
        "accepted_matching_mode": 2,
        "accepted_after_confirmation": 2,
    }
    last_request = response.checks["recent_evidence"].metadata["last_request"]
    assert isinstance(last_request, dict)
    assert last_request["requester"] == "production_smoke"
    assert last_request["selected_tool"] == "search"
    assert last_request["status"] == "succeeded"
    quality_canary = response.checks["recent_evidence"].metadata["quality_canary"]
    assert quality_canary["request_id"]
    assert quality_canary == {
        "request_id": quality_canary["request_id"],
        "status": "passed",
        "suite": "beacon_search_quality",
        "suite_version": 2,
        "case_count": 33,
        "passed": 33,
        "failed": 0,
        "failure_names": [],
        "last_run_at": quality_canary["last_run_at"],
    }
    assert response.retention.mode == "report_only"


@pytest.mark.asyncio
async def test_health_parses_quality_canary_json_metadata(monkeypatch):
    monkeypatch.setattr(
        beacon_health,
        "browser_runtime_health",
        lambda: {
            "ok": True,
            "runtime": "playwright",
            "runtime_enabled": True,
            "playwright_version_ok": True,
            "screenshot_dir_writable": True,
        },
    )
    request_id = uuid4()

    response = await beacon_health.build_beacon_health(
        FakeConn(
            quality_canary_row={
                "request_id": request_id,
                "status": "succeeded",
                "created_at": datetime(2026, 6, 15, 13, 42, tzinfo=UTC),
                "metadata": json.dumps(
                    {
                        "request_id": str(request_id),
                        "suite": "beacon_search_quality",
                        "suite_version": 2,
                        "case_count": 33,
                        "passed": 33,
                        "failed": 0,
                        "failure_names": [],
                        "status": "passed",
                    }
                ),
            }
        ),
        gateway_client=FakeGatewayClient(),
    )

    quality_canary = response.checks["recent_evidence"].metadata["quality_canary"]
    assert quality_canary == {
        "request_id": str(request_id),
        "status": "passed",
        "suite": "beacon_search_quality",
        "suite_version": 2,
        "case_count": 33,
        "passed": 33,
        "failed": 0,
        "failure_names": [],
        "last_run_at": "2026-06-15T13:42:00+00:00",
    }


@pytest.mark.asyncio
async def test_health_keeps_recent_evidence_failure_as_warning(monkeypatch):
    monkeypatch.setattr(
        beacon_health,
        "browser_runtime_health",
        lambda: {
            "ok": True,
            "runtime": "playwright",
            "runtime_enabled": True,
            "playwright_version_ok": True,
            "screenshot_dir_writable": True,
        },
    )

    response = await beacon_health.build_beacon_health(
        FakeConn(
            recent_row={
                "total": 10,
                "succeeded": 8,
                "failed": 1,
                "blocked": 1,
            }
        ),
        gateway_client=FakeGatewayClient(),
    )

    assert response.status == "ok"
    assert response.checks["recent_evidence"].ok is False
    assert response.checks["recent_evidence"].status == "degraded"
    assert response.checks["recent_evidence"].metadata["failed"] == 1


@pytest.mark.asyncio
async def test_health_degrades_when_core_gateway_check_fails(monkeypatch):
    monkeypatch.setattr(
        beacon_health,
        "browser_runtime_health",
        lambda: {
            "ok": True,
            "runtime": "playwright",
            "runtime_enabled": True,
            "playwright_version_ok": True,
            "screenshot_dir_writable": True,
        },
    )

    response = await beacon_health.build_beacon_health(
        FakeConn(),
        gateway_client=FakeGatewayClient(usable_provider_count=0),
    )

    assert response.status == "degraded"
    assert response.checks["gateway"].ok is False
