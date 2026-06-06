from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os

import pytest

from brain.services.internet_scout import health as beacon_health
from brain.services.internet_scout.retention import build_retention_report


class FakeConn:
    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.counts = counts or {}

    async def fetchval(self, query: str, *args):
        if "to_regclass" in query:
            return args[0]
        if "to_regprocedure" in query:
            return args[0]
        for table, count in self.counts.items():
            if f"public.{table}" in query:
                return count
        return 0

    async def fetchrow(self, query: str, *args):
        return {
            "total": 3,
            "succeeded": 2,
            "failed": 0,
            "blocked": 1,
        }


class FakeGatewayClient:
    async def health(self):
        return {
            "status": "ok",
            "provider_order": ["brave", "perplexity"],
            "configured_provider_count": 2,
            "usable_provider_count": 2,
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
    assert response.retention.mode == "report_only"
