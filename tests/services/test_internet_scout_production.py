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
        latency_row: dict[str, int] | None = None,
        suggestion_row: dict[str, int] | None = None,
        acceptance_row: dict[str, int] | None = None,
        web_cache_row: dict[str, object] | None = None,
        crawler_row: dict[str, object] | None = None,
        quality_canary_row: dict[str, object] | None = None,
        quality_canary_rows: list[dict[str, object]] | None = None,
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
        self.latency_row = latency_row or {
            "sample_count": 3,
            "avg_ms": 1000,
            "p95_ms": 2400,
            "max_ms": 2600,
            "slow_request_count": 1,
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
        self.web_cache_row = web_cache_row or {
            "active_entry_count": 4,
            "expired_entry_count": 1,
            "total_hit_count": 7,
            "last_hit_at": now,
            "last_seen_at": now,
        }
        self.crawler_row = crawler_row or {
            "request_count": 4,
            "succeeded_request_count": 2,
            "failed_request_count": 1,
            "blocked_host_count": 1,
            "cache_hit_count": 1,
            "cache_miss_count": 1,
            "failed_page_count": 1,
            "source_count": 3,
            "claim_count": 5,
            "render_request_count": 4,
            "render_ok_count": 2,
            "render_weak_count": 1,
            "render_empty_count": 1,
            "render_missing_screenshot_count": 1,
            "render_missing_evidence_count": 1,
            "crawl_request_count": 4,
            "crawl_page_cap_hit_count": 2,
            "crawl_depth_cap_hit_count": 0,
            "crawl_time_cap_hit_count": 0,
            "last_run_at": now,
        }
        self.quality_canary_row = quality_canary_row or {
            "request_id": uuid4(),
            "status": "succeeded",
            "created_at": now,
            "metadata": {
                "suite": "beacon_search_quality",
                "suite_version": 2,
                "case_count": 34,
                "passed": 34,
                "failed": 0,
                "failure_names": [],
                "status": "passed",
                "case_groups": {
                    "core": {
                        "case_count": 30,
                        "passed": 30,
                        "failed": 0,
                        "failure_names": [],
                        "case_names": [],
                    },
                    "daily_use": {
                        "case_count": 4,
                        "passed": 4,
                        "failed": 0,
                        "failure_names": [],
                        "case_names": [],
                    },
                },
            },
        }
        self.quality_canary_rows = quality_canary_rows or [self.quality_canary_row]

    async def fetchval(self, query: str, *args):
        if "to_regclass" in query:
            return args[0]
        if "to_regprocedure" in query:
            return args[0]
        if "alpha_internet_web_cache" in query and "expires_at <= NOW()" in query:
            return self.counts.get("alpha_internet_web_cache", 0)
        for table, count in self.counts.items():
            if f"public.{table}" in query:
                return count
        return 0

    async def fetch(self, query: str, *args):
        if "quality_canary" in query:
            return self.quality_canary_rows
        if "FROM public.alpha_internet_requests" in query:
            return [{"id": request_id} for request_id in self.expired_request_ids]
        return []

    async def fetchrow(self, query: str, *args):
        if "event_type LIKE 'crawler_%'" in query:
            return self.crawler_row
        if "FROM public.alpha_internet_web_cache" in query:
            return self.web_cache_row
        if "quality_canary" in query:
            return self.quality_canary_row
        if "chat_web_suggestion_acceptance" in query:
            return self.acceptance_row
        if "FROM public.chat_messages" in query:
            return self.suggestion_row
        if "chat_evidence_quality" in query:
            return self.quality_row
        if "PERCENTILE_CONT" in query:
            return self.latency_row
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
    def __init__(
        self,
        *,
        usable_provider_count: int = 2,
        backup_budget_guard_warning: bool = False,
    ) -> None:
        self.usable_provider_count = usable_provider_count
        self.backup_budget_guard_warning = backup_budget_guard_warning

    async def health(self):
        providers = [
            {
                "provider": "brave",
                "configured": True,
                "circuit_open": False,
                "budget_exhausted": False,
            },
            {
                "provider": "perplexity",
                "configured": True,
                "circuit_open": False,
                "budget_exhausted": False,
            },
        ]
        usable_provider_count = self.usable_provider_count
        if self.backup_budget_guard_warning:
            usable_provider_count = 1
            providers[1]["budget_exhausted"] = True
        else:
            for provider in providers[usable_provider_count:]:
                provider["circuit_open"] = True
        required_count = 2
        redundancy_ok = usable_provider_count >= required_count
        warning_status = (
            "backup_budget_capped" if self.backup_budget_guard_warning else None
        )
        return {
            "status": "warning"
            if self.backup_budget_guard_warning
            else "ok"
            if usable_provider_count and redundancy_ok
            else "degraded",
            "provider_order": ["brave", "perplexity"],
            "configured_provider_count": 2,
            "usable_provider_count": usable_provider_count,
            "required_provider_count": required_count,
            "provider_redundancy_ok": redundancy_ok,
            "provider_redundancy_status": "redundant"
            if redundancy_ok
            else "backup_budget_capped"
            if self.backup_budget_guard_warning
            else "single_provider"
            if usable_provider_count
            else "unavailable",
            "missing_provider_count": max(0, required_count - usable_provider_count),
            "provider_warning_status": warning_status,
            "primary_provider": "brave",
            "primary_provider_usable": usable_provider_count > 0
            and not providers[0]["circuit_open"]
            and not providers[0]["budget_exhausted"],
            "budget_capped_provider_count": 1
            if self.backup_budget_guard_warning
            else 0,
            "budget_capped_backup_provider_count": 1
            if self.backup_budget_guard_warning
            else 0,
            "providers": providers,
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
                "alpha_internet_web_cache": 9,
            }
        )
    )

    assert report.mode == "report_only"
    assert report.evidence_retention_days == 30
    assert report.old_request_count == 4
    assert report.old_event_count == 7
    assert report.old_memory_promotion_count == 8
    assert report.expired_web_cache_entry_count == 9
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
            "alpha_internet_web_cache": 5,
        },
        counts={"alpha_internet_web_cache": 5},
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
    assert response.candidate_web_cache_entry_count == 5
    assert response.deleted_web_cache_entry_count == 5
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
    assert response.checks["gateway"].metadata["required_provider_count"] == 2
    assert response.checks["gateway"].metadata["provider_redundancy_ok"] is True
    assert (
        response.checks["gateway"].metadata["provider_redundancy_status"] == "redundant"
    )
    assert response.checks["browser_runtime"].ok is True
    assert response.checks["web_cache"].ok is True
    assert response.checks["web_cache"].status == "ok"
    assert response.checks["web_cache"].metadata["active_entry_count"] == 4
    assert response.checks["web_cache"].metadata["raw_user_query_stored"] is False
    assert response.checks["crawler"].ok is True
    assert response.checks["crawler"].status == "warning"
    assert response.checks["crawler"].metadata == {
        "mode": "gateway_bounded_crawler",
        "window_hours": 24,
        "request_count": 4,
        "succeeded_request_count": 2,
        "failed_request_count": 1,
        "blocked_host_count": 1,
        "cache_hit_count": 1,
        "cache_miss_count": 1,
        "cache_hit_rate_percent": 50,
        "failed_page_count": 1,
        "source_count": 3,
        "claim_count": 5,
        "render_quality_version": 2,
        "render_request_count": 4,
        "render_ok_count": 2,
        "render_weak_count": 1,
        "render_empty_count": 1,
        "render_weak_empty_count": 2,
        "render_weak_empty_rate_percent": 50,
        "render_missing_screenshot_count": 1,
        "render_missing_evidence_count": 1,
        "render_quality_watch_status": "action",
        "render_quality_next_action": "add_render_retry_or_site_tuning",
        "render_quality_watch_reason": "render_quality_signal_above_threshold",
        "crawl_request_count": 4,
        "crawl_page_cap_hit_count": 2,
        "crawl_depth_cap_hit_count": 0,
        "crawl_time_cap_hit_count": 0,
        "crawl_cap_pressure_count": 2,
        "crawl_cap_pressure_rate_percent": 50,
        "async_crawl_jobs_status": "recommended",
        "async_crawl_jobs_next_action": "plan_async_crawl_jobs",
        "async_crawl_jobs_reason": "crawl_cap_pressure_above_threshold",
        "last_run_at": response.checks["crawler"].metadata["last_run_at"],
        "max_pages_without_approval": 10,
        "max_depth_without_approval": 2,
        "same_host_required": True,
        "forms_allowed": False,
        "credential_entry_allowed": False,
        "raw_web_content_is_untrusted": True,
    }
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
    assert response.checks["recent_evidence"].metadata["latency"] == {
        "window_hours": 24,
        "sample_count": 3,
        "avg_ms": 1000,
        "p95_ms": 2400,
        "max_ms": 2600,
        "slo_target_ms": 20000,
        "slow_request_count": 1,
        "slo_met_percent": 67,
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
        "case_count": 34,
        "passed": 34,
        "failed": 0,
        "failure_names": [],
        "case_groups": {
            "core": {
                "case_count": 30,
                "passed": 30,
                "failed": 0,
                "failure_names": [],
                "case_names": [],
            },
            "daily_use": {
                "case_count": 4,
                "passed": 4,
                "failed": 0,
                "failure_names": [],
                "case_names": [],
            },
        },
        "last_run_at": quality_canary["last_run_at"],
        "age_hours": quality_canary["age_hours"],
        "expected_interval_hours": 24,
        "next_due_at": quality_canary["next_due_at"],
        "schedule_status": "ok",
        "stale_after_hours": 26,
        "alert": {
            "status": "ok",
            "reason": "quality_canary_fresh",
            "severity": "info",
        },
    }
    assert response.checks["quality_canary"].ok is True
    assert response.checks["quality_canary"].status == "ok"
    assert (
        response.checks["recent_evidence"].metadata["quality_canary_history"][0][
            "passed"
        ]
        == 34
    )
    assert (
        response.checks["recent_evidence"].metadata["quality_canary_trend"]["trend"]
        == "single_sample"
    )
    assert response.retention.mode == "report_only"


@pytest.mark.asyncio
async def test_crawler_watch_signals_do_not_recommend_work_without_pressure(
    monkeypatch,
):
    monkeypatch.setattr(
        beacon_health,
        "browser_runtime_health",
        lambda: {"ok": True, "runtime_enabled": True},
    )
    now = datetime.now(UTC)
    conn = FakeConn(
        crawler_row={
            "request_count": 1,
            "succeeded_request_count": 1,
            "failed_request_count": 0,
            "blocked_host_count": 0,
            "cache_hit_count": 0,
            "cache_miss_count": 1,
            "failed_page_count": 0,
            "source_count": 1,
            "claim_count": 1,
            "render_request_count": 0,
            "render_ok_count": 0,
            "render_weak_count": 0,
            "render_empty_count": 0,
            "render_missing_screenshot_count": 0,
            "render_missing_evidence_count": 0,
            "crawl_request_count": 1,
            "crawl_page_cap_hit_count": 0,
            "crawl_depth_cap_hit_count": 0,
            "crawl_time_cap_hit_count": 0,
            "last_run_at": now,
        }
    )

    response = await beacon_health.build_beacon_health(
        conn,
        gateway_client=FakeGatewayClient(),
    )

    crawler = response.checks["crawler"]
    assert crawler.status == "ok"
    assert crawler.metadata["render_quality_watch_status"] == "observe"
    assert (
        crawler.metadata["render_quality_next_action"]
        == "watch_real_approved_render_usage"
    )
    assert crawler.metadata["async_crawl_jobs_status"] == "not_needed"
    assert crawler.metadata["async_crawl_jobs_next_action"] == "keep_sync_crawler"


@pytest.mark.asyncio
async def test_crawler_cap_watch_signal_does_not_fail_health(monkeypatch):
    monkeypatch.setattr(
        beacon_health,
        "browser_runtime_health",
        lambda: {"ok": True, "runtime_enabled": True},
    )
    now = datetime.now(UTC)
    conn = FakeConn(
        crawler_row={
            "request_count": 32,
            "succeeded_request_count": 32,
            "failed_request_count": 0,
            "blocked_host_count": 0,
            "cache_hit_count": 1,
            "cache_miss_count": 1,
            "failed_page_count": 0,
            "source_count": 32,
            "claim_count": 32,
            "render_request_count": 0,
            "render_ok_count": 0,
            "render_weak_count": 0,
            "render_empty_count": 0,
            "render_missing_screenshot_count": 0,
            "render_missing_evidence_count": 0,
            "crawl_request_count": 32,
            "crawl_page_cap_hit_count": 2,
            "crawl_depth_cap_hit_count": 0,
            "crawl_time_cap_hit_count": 0,
            "last_run_at": now,
        }
    )

    response = await beacon_health.build_beacon_health(
        conn,
        gateway_client=FakeGatewayClient(),
    )

    crawler = response.checks["crawler"]
    assert crawler.status == "ok"
    assert crawler.metadata["crawl_cap_pressure_count"] == 2
    assert crawler.metadata["crawl_cap_pressure_rate_percent"] == 6
    assert crawler.metadata["async_crawl_jobs_status"] == "watch"
    assert (
        crawler.metadata["async_crawl_jobs_next_action"] == "watch_cap_pressure_trend"
    )


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

    checked_at = datetime.now(UTC)
    response = await beacon_health.build_beacon_health(
        FakeConn(
            quality_canary_row={
                "request_id": request_id,
                "status": "succeeded",
                "created_at": checked_at,
                "metadata": json.dumps(
                    {
                        "request_id": str(request_id),
                        "suite": "beacon_search_quality",
                        "suite_version": 2,
                        "case_count": 34,
                        "passed": 34,
                        "failed": 0,
                        "failure_names": [],
                        "status": "passed",
                        "case_groups": {
                            "daily_use": {
                                "case_count": 4,
                                "passed": 4,
                                "failed": 0,
                                "failure_names": [],
                                "case_names": [],
                            }
                        },
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
        "case_count": 34,
        "passed": 34,
        "failed": 0,
        "failure_names": [],
        "case_groups": {
            "daily_use": {
                "case_count": 4,
                "passed": 4,
                "failed": 0,
                "failure_names": [],
                "case_names": [],
            }
        },
        "last_run_at": checked_at.isoformat(),
        "age_hours": 0,
        "expected_interval_hours": 24,
        "next_due_at": (checked_at + timedelta(hours=24)).isoformat(),
        "schedule_status": "ok",
        "stale_after_hours": 26,
        "alert": {
            "status": "ok",
            "reason": "quality_canary_fresh",
            "severity": "info",
        },
    }


@pytest.mark.asyncio
async def test_health_reports_quality_canary_history_trend(monkeypatch):
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
    now = datetime.now(UTC)

    def row(*, passed: int, failed: int, precision: float, elapsed_ms: int, hours: int):
        return {
            "request_id": uuid4(),
            "status": "succeeded" if failed == 0 else "failed",
            "created_at": now - timedelta(hours=hours),
            "metadata": {
                "suite": "beacon_search_quality",
                "suite_version": 2,
                "case_count": passed + failed,
                "passed": passed,
                "failed": failed,
                "failure_names": [],
                "status": "passed" if failed == 0 else "failed",
                "case_groups": {},
                "answer_engine": {
                    "status": "passed" if failed == 0 else "failed",
                    "passed": 15,
                    "failed": failed,
                    "reporting": {
                        "latency": {"suite_elapsed_ms": elapsed_ms},
                        "cost": {"estimated_provider_cost_usd": 0.0},
                        "citation_precision": {"precision": precision},
                    },
                },
            },
        }

    response = await beacon_health.build_beacon_health(
        FakeConn(
            quality_canary_rows=[
                row(passed=40, failed=0, precision=0.9, elapsed_ms=20, hours=1),
                row(passed=38, failed=2, precision=0.75, elapsed_ms=30, hours=25),
            ]
        ),
        gateway_client=FakeGatewayClient(),
    )

    trend = response.checks["recent_evidence"].metadata["quality_canary_trend"]
    assert trend == {
        "window_runs": 2,
        "passed_runs": 1,
        "failed_runs": 1,
        "pass_rate_percent": 50,
        "latest_failed": 0,
        "failed_delta": -2,
        "passed_delta": 2,
        "case_count_delta": 0,
        "latest_precision": 0.9,
        "precision_delta": 0.15,
        "latest_suite_elapsed_ms": 20,
        "latency_delta_ms": -10,
        "estimated_provider_cost_usd": 0.0,
        "trend": "improving",
    }


@pytest.mark.asyncio
async def test_health_degrades_when_quality_canary_is_failed(monkeypatch):
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
            quality_canary_row={
                "request_id": uuid4(),
                "status": "succeeded",
                "created_at": datetime.now(UTC),
                "metadata": {
                    "suite": "beacon_search_quality",
                    "suite_version": 2,
                    "case_count": 34,
                    "passed": 33,
                    "failed": 1,
                    "failure_names": ["official_openai_source_beats_community"],
                    "status": "failed",
                },
            }
        ),
        gateway_client=FakeGatewayClient(),
    )

    assert response.status == "degraded"
    assert response.checks["quality_canary"].ok is False
    assert response.checks["quality_canary"].metadata["alert_status"] == "failed"
    assert response.checks["recent_evidence"].metadata["quality_canary"]["alert"] == {
        "status": "failed",
        "reason": "quality_canary_failed",
        "severity": "warning",
    }


@pytest.mark.asyncio
async def test_health_degrades_when_quality_canary_is_stale(monkeypatch):
    monkeypatch.setenv("BEACON_QUALITY_CANARY_STALE_AFTER_HOURS", "24")
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
            quality_canary_row={
                "request_id": uuid4(),
                "status": "succeeded",
                "created_at": datetime.now(UTC) - timedelta(hours=30),
                "metadata": {
                    "suite": "beacon_search_quality",
                    "suite_version": 2,
                    "case_count": 34,
                    "passed": 34,
                    "failed": 0,
                    "failure_names": [],
                    "status": "passed",
                },
            }
        ),
        gateway_client=FakeGatewayClient(),
    )

    assert response.status == "degraded"
    assert response.checks["quality_canary"].ok is False
    assert response.checks["quality_canary"].metadata["alert_status"] == "stale"
    quality_canary = response.checks["recent_evidence"].metadata["quality_canary"]
    assert quality_canary["alert"]["reason"] == "quality_canary_stale"
    assert quality_canary["age_hours"] >= 30
    assert quality_canary["schedule_status"] == "stale"
    assert quality_canary["stale_after_hours"] == 24


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
    assert (
        response.checks["gateway"].metadata["provider_redundancy_status"]
        == "unavailable"
    )


@pytest.mark.asyncio
async def test_health_degrades_when_gateway_provider_redundancy_is_missing(
    monkeypatch,
):
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
        gateway_client=FakeGatewayClient(usable_provider_count=1),
    )

    gateway = response.checks["gateway"]
    assert response.status == "degraded"
    assert gateway.ok is False
    assert gateway.status == "degraded"
    assert gateway.metadata["usable_provider_count"] == 1
    assert gateway.metadata["required_provider_count"] == 2
    assert gateway.metadata["provider_redundancy_ok"] is False
    assert gateway.metadata["provider_redundancy_status"] == "single_provider"
    assert gateway.metadata["missing_provider_count"] == 1


@pytest.mark.asyncio
async def test_health_warns_when_backup_provider_is_budget_capped(monkeypatch):
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
        gateway_client=FakeGatewayClient(backup_budget_guard_warning=True),
    )

    gateway = response.checks["gateway"]
    assert response.status == "ok"
    assert gateway.ok is True
    assert gateway.status == "warning"
    assert gateway.detail == (
        "Gateway has 1 usable search provider(s); backup provider is capped by "
        "spend guard."
    )
    assert gateway.metadata["gateway_status"] == "warning"
    assert gateway.metadata["usable_provider_count"] == 1
    assert gateway.metadata["required_provider_count"] == 2
    assert gateway.metadata["provider_redundancy_ok"] is False
    assert gateway.metadata["provider_redundancy_status"] == "backup_budget_capped"
    assert gateway.metadata["provider_warning_status"] == "backup_budget_capped"
    assert gateway.metadata["primary_provider"] == "brave"
    assert gateway.metadata["primary_provider_usable"] is True
    assert gateway.metadata["budget_capped_backup_provider_count"] == 1
