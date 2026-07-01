from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BEACON_PAGE = REPO_ROOT / "ui" / "src" / "pages" / "Beacon.tsx"
CRAWLER_CONSOLE = (
    REPO_ROOT / "ui" / "src" / "components" / "beacon" / "BeaconCrawlerConsole.tsx"
)
BEACON_TYPES = REPO_ROOT / "ui" / "src" / "types" / "beacon.ts"


def test_beacon_mounts_compact_crawler_console() -> None:
    source = BEACON_PAGE.read_text(encoding="utf-8")
    console = CRAWLER_CONSOLE.read_text(encoding="utf-8")

    assert "BeaconCrawlerConsole" in source
    assert "Crawler console" in console
    assert "Scrape, map, crawl, extract, render" in console
    assert "Cache first" in console
    assert "Same host" in console
    assert "No forms" in console
    assert "No credentials" in console


def test_crawler_console_calls_all_existing_crawler_endpoints() -> None:
    console = CRAWLER_CONSOLE.read_text(encoding="utf-8")

    assert "/v1/internet-scout/crawler/scrape" in console
    assert "/v1/internet-scout/crawler/map" in console
    assert "/v1/internet-scout/crawler/crawl" in console
    assert "/v1/internet-scout/crawler/extract" in console
    assert "/v1/internet-scout/crawler/scrape/browser-approval-request" in console
    assert "/v1/internet-scout/crawler/scrape/browser-run-approved" in console
    assert "Queue render approval" in console
    assert "Run approved render" in console
    assert 'to="/approvals"' in console


def test_crawler_console_surfaces_compact_results_and_safety_context() -> None:
    console = CRAWLER_CONSOLE.read_text(encoding="utf-8")
    types = BEACON_TYPES.read_text(encoding="utf-8")

    assert "Result summary" in console
    assert "Text excerpt and links" in console
    assert "Pages and same-host links" in console
    assert "Why stopped" in console
    assert "Link groups by host" in console
    assert "Blocked / robots markers" in console
    assert "Same-host crawl capped" in console
    assert "Fields and evidence" in console
    assert "Render evidence" in console
    assert "raw_web_content_is_untrusted" in console
    assert "BeaconCrawlerMode" in types
    assert "BeaconCrawlerRenderResponse" in types
    assert "evidence_path" in types
    assert "audit_path" in types


def test_crawler_console_has_history_search_and_evidence_export() -> None:
    console = CRAWLER_CONSOLE.read_text(encoding="utf-8")
    types = BEACON_TYPES.read_text(encoding="utf-8")

    assert "Crawler history and export" in console
    assert "/v1/internet-scout/requests?" in console
    assert "/v1/internet-scout/requests/${requestId}" in console
    assert "Search crawler request, host, status" in console
    assert "Export evidence" in console
    assert "beacon-crawler-evidence-" in console
    assert "crawler_cache_hit" in types
    assert "crawler_blocked_reasons" in types
