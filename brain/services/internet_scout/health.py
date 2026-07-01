"""Production readiness checks for Beacon internet-scout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from typing import Protocol

from brain.services.internet_scout.browser_runner import browser_runtime_health
from brain.services.internet_scout.gateway_client import (
    InternetScoutGatewayClient,
    InternetScoutGatewayError,
)
from brain.services.internet_scout.models import (
    InternetScoutHealthCheck,
    InternetScoutHealthResponse,
)
from brain.services.internet_scout.policy import (
    CRAWL_MAX_DEPTH_WITHOUT_APPROVAL,
    CRAWL_MAX_PAGES_WITHOUT_APPROVAL,
)
from brain.services.internet_scout.retention import build_retention_report

_REQUIRED_TABLES = (
    "alpha_internet_requests",
    "alpha_internet_sources",
    "alpha_internet_evidence",
    "alpha_internet_tool_events",
    "alpha_internet_memory_promotions",
    "alpha_internet_web_cache",
)
_REQUIRED_FUNCTIONS = ("public.save_beacon_semantic_memory(uuid,text,text,text,text)",)
_READINESS_CHECKS = (
    "database",
    "gateway",
    "browser_runtime",
    "retention",
    "quality_canary",
    "web_cache",
)
_QUALITY_CANARY_HISTORY_LIMIT = 7
_QUALITY_CANARY_STALE_AFTER_HOURS = 26
_DEFAULT_ANSWER_LATENCY_SLO_MS = 20_000
_RENDER_ACTION_MIN_RUNS = 3
_RENDER_ACTION_WEAK_EMPTY_RATE_PERCENT = 50
_RENDER_ACTION_MISSING_COUNT = 2
_CRAWL_CAP_ACTION_MIN_RUNS = 3
_CRAWL_CAP_ACTION_RATE_PERCENT = 50
_CRAWL_CAP_ACTION_COUNT = 3


class _RequestRow(Protocol):
    def __getitem__(self, key: str) -> object: ...


async def build_beacon_health(
    conn,
    *,
    gateway_client: InternetScoutGatewayClient | None = None,
) -> InternetScoutHealthResponse:
    checked_at = datetime.now(UTC)
    checks = {
        "database": await _database_check(conn),
        "gateway": await _gateway_check(gateway_client or InternetScoutGatewayClient()),
        "browser_runtime": _browser_runtime_check(),
        "recent_evidence": await _recent_evidence_check(conn, checked_at=checked_at),
        "web_cache": await _web_cache_check(conn),
        "crawler": await _crawler_check(conn),
    }
    checks["quality_canary"] = _quality_canary_check(
        checks["recent_evidence"].metadata,
    )
    retention = await build_retention_report(conn)
    checks["retention"] = InternetScoutHealthCheck(
        ok=True,
        status="ok",
        detail="Retention inventory is report-only.",
        metadata={
            "mode": retention.mode,
            "evidence_retention_days": retention.evidence_retention_days,
            "screenshot_retention_days": retention.screenshot_retention_days,
            "old_request_count": retention.old_request_count,
            "screenshot_file_count": retention.screenshot_file_count,
        },
    )
    readiness_ok = all(checks[name].ok for name in _READINESS_CHECKS)
    return InternetScoutHealthResponse(
        status="ok" if readiness_ok else "degraded",
        checks=checks,
        retention=retention,
        checked_at=checked_at,
    )


async def _web_cache_check(conn) -> InternetScoutHealthCheck:
    if not await _table_exists(conn, "alpha_internet_web_cache"):
        return InternetScoutHealthCheck(
            ok=False,
            status="unavailable",
            detail="Beacon web cache table is missing.",
            metadata={"table": "alpha_internet_web_cache"},
        )
    metadata = await _web_cache_metadata(conn)
    active_entry_count = _int_mapping(metadata, "active_entry_count")
    return InternetScoutHealthCheck(
        ok=True,
        status="ok" if active_entry_count else "warning",
        detail="Beacon web cache is ready."
        if active_entry_count
        else "Beacon web cache is ready and waiting for warm evidence.",
        metadata=metadata,
    )


async def _crawler_check(conn) -> InternetScoutHealthCheck:
    if not await _table_exists(conn, "alpha_internet_tool_events"):
        return InternetScoutHealthCheck(
            ok=False,
            status="unavailable",
            detail="Beacon crawler audit table is missing.",
            metadata={"table": "alpha_internet_tool_events"},
        )
    metadata = await _crawler_metadata(conn)
    failed = _int_mapping(metadata, "failed_request_count")
    blocked = _int_mapping(metadata, "blocked_host_count")
    render_watch = str(metadata.get("render_quality_watch_status") or "observe")
    async_jobs = str(metadata.get("async_crawl_jobs_status") or "not_needed")
    status = (
        "warning"
        if failed or blocked or render_watch == "action" or async_jobs == "recommended"
        else "ok"
    )
    return InternetScoutHealthCheck(
        ok=True,
        status=status,
        detail="Beacon crawler is bounded and audited.",
        metadata=metadata,
    )


async def _crawler_metadata(conn) -> dict[str, object]:
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE event_type LIKE 'crawler_%')::INTEGER
                AS request_count,
            COUNT(*) FILTER (
                WHERE event_type LIKE 'crawler_%' AND status = 'succeeded'
            )::INTEGER AS succeeded_request_count,
            COUNT(*) FILTER (
                WHERE event_type LIKE 'crawler_%' AND status = 'failed'
            )::INTEGER AS failed_request_count,
            COUNT(*) FILTER (
                WHERE event_type LIKE 'crawler_%' AND status = 'blocked'
            )::INTEGER AS blocked_host_count,
            COUNT(*) FILTER (
                WHERE event_type LIKE 'crawler_%'
                  AND metadata->>'cache_hit' = 'true'
            )::INTEGER AS cache_hit_count,
            COUNT(*) FILTER (
                WHERE event_type LIKE 'crawler_%'
                  AND metadata->>'cache_hit' = 'false'
            )::INTEGER AS cache_miss_count,
            COALESCE(SUM(
                CASE
                    WHEN metadata->>'failed_page_count' ~ '^[0-9]+$'
                    THEN (metadata->>'failed_page_count')::INTEGER
                    ELSE 0
                END
            ), 0)::INTEGER AS failed_page_count,
            COALESCE(SUM(
                CASE
                    WHEN metadata->>'source_count' ~ '^[0-9]+$'
                    THEN (metadata->>'source_count')::INTEGER
                    ELSE 0
                END
            ), 0)::INTEGER AS source_count,
            COALESCE(SUM(
                CASE
                    WHEN metadata->>'claim_count' ~ '^[0-9]+$'
                    THEN (metadata->>'claim_count')::INTEGER
                    ELSE 0
                END
            ), 0)::INTEGER AS claim_count,
            COUNT(*) FILTER (
                WHERE event_type = 'browser_run'
                  AND metadata->>'source' = 'crawler_render_scrape'
                  AND metadata->>'render_quality_version' = '2'
            )::INTEGER AS render_request_count,
            COUNT(*) FILTER (
                WHERE event_type = 'browser_run'
                  AND metadata->>'source' = 'crawler_render_scrape'
                  AND metadata->>'render_quality_status' = 'ok'
            )::INTEGER AS render_ok_count,
            COUNT(*) FILTER (
                WHERE event_type = 'browser_run'
                  AND metadata->>'source' = 'crawler_render_scrape'
                  AND metadata->>'render_quality_status' = 'weak'
            )::INTEGER AS render_weak_count,
            COUNT(*) FILTER (
                WHERE event_type = 'browser_run'
                  AND metadata->>'source' = 'crawler_render_scrape'
                  AND metadata->>'render_quality_status' = 'empty'
            )::INTEGER AS render_empty_count,
            COUNT(*) FILTER (
                WHERE event_type = 'browser_run'
                  AND metadata->>'source' = 'crawler_render_scrape'
                  AND metadata->>'missing_screenshot' = 'true'
            )::INTEGER AS render_missing_screenshot_count,
            COUNT(*) FILTER (
                WHERE event_type = 'browser_run'
                  AND metadata->>'source' = 'crawler_render_scrape'
                  AND metadata->>'missing_evidence' = 'true'
            )::INTEGER AS render_missing_evidence_count,
            COUNT(*) FILTER (
                WHERE event_type IN ('crawler_map', 'crawler_crawl')
                  AND status = 'succeeded'
            )::INTEGER AS crawl_request_count,
            COUNT(*) FILTER (
                WHERE event_type IN ('crawler_map', 'crawler_crawl')
                  AND status = 'succeeded'
                  AND (
                    metadata->>'page_cap_hit' = 'true'
                    OR CASE
                        WHEN metadata->>'page_count' ~ '^[0-9]+$'
                         AND metadata->>'max_pages' ~ '^[0-9]+$'
                        THEN (metadata->>'page_count')::INTEGER
                            >= (metadata->>'max_pages')::INTEGER
                        ELSE FALSE
                    END
                  )
            )::INTEGER AS crawl_page_cap_hit_count,
            COUNT(*) FILTER (
                WHERE event_type IN ('crawler_map', 'crawler_crawl')
                  AND status = 'succeeded'
                  AND metadata->>'depth_cap_hit' = 'true'
            )::INTEGER AS crawl_depth_cap_hit_count,
            COUNT(*) FILTER (
                WHERE event_type IN ('crawler_map', 'crawler_crawl')
                  AND status = 'succeeded'
                  AND metadata->>'time_cap_hit' = 'true'
            )::INTEGER AS crawl_time_cap_hit_count,
            MAX(created_at) AS last_run_at
        FROM public.alpha_internet_tool_events
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        """
    )
    hits = _int_row(row, "cache_hit_count") if row else 0
    misses = _int_row(row, "cache_miss_count") if row else 0
    cache_total = hits + misses
    render_total = _int_row(row, "render_request_count") if row else 0
    render_weak = _int_row(row, "render_weak_count") if row else 0
    render_empty = _int_row(row, "render_empty_count") if row else 0
    render_weak_empty = render_weak + render_empty
    missing_screenshots = _int_row(row, "render_missing_screenshot_count") if row else 0
    missing_evidence = _int_row(row, "render_missing_evidence_count") if row else 0
    render_rate = round((render_weak_empty / render_total) * 100) if render_total else 0
    render_watch = _render_quality_watch(
        render_total=render_total,
        weak_empty_rate_percent=render_rate,
        missing_screenshot_count=missing_screenshots,
        missing_evidence_count=missing_evidence,
    )
    crawl_requests = _int_row(row, "crawl_request_count") if row else 0
    page_cap_hits = _int_row(row, "crawl_page_cap_hit_count") if row else 0
    depth_cap_hits = _int_row(row, "crawl_depth_cap_hit_count") if row else 0
    time_cap_hits = _int_row(row, "crawl_time_cap_hit_count") if row else 0
    cap_pressure_count = page_cap_hits + depth_cap_hits + time_cap_hits
    cap_pressure_rate = (
        round((cap_pressure_count / crawl_requests) * 100) if crawl_requests else 0
    )
    async_jobs = _async_crawl_jobs_watch(
        crawl_request_count=crawl_requests,
        cap_pressure_count=cap_pressure_count,
        cap_pressure_rate_percent=cap_pressure_rate,
    )
    return {
        "mode": "gateway_bounded_crawler",
        "window_hours": 24,
        "request_count": _int_row(row, "request_count") if row else 0,
        "succeeded_request_count": _int_row(row, "succeeded_request_count")
        if row
        else 0,
        "failed_request_count": _int_row(row, "failed_request_count") if row else 0,
        "blocked_host_count": _int_row(row, "blocked_host_count") if row else 0,
        "cache_hit_count": hits,
        "cache_miss_count": misses,
        "cache_hit_rate_percent": round((hits / cache_total) * 100)
        if cache_total
        else 0,
        "failed_page_count": _int_row(row, "failed_page_count") if row else 0,
        "source_count": _int_row(row, "source_count") if row else 0,
        "claim_count": _int_row(row, "claim_count") if row else 0,
        "render_quality_version": 2,
        "render_request_count": render_total,
        "render_ok_count": _int_row(row, "render_ok_count") if row else 0,
        "render_weak_count": render_weak,
        "render_empty_count": render_empty,
        "render_weak_empty_count": render_weak_empty,
        "render_weak_empty_rate_percent": render_rate,
        "render_missing_screenshot_count": missing_screenshots,
        "render_missing_evidence_count": missing_evidence,
        **render_watch,
        "crawl_request_count": crawl_requests,
        "crawl_page_cap_hit_count": page_cap_hits,
        "crawl_depth_cap_hit_count": depth_cap_hits,
        "crawl_time_cap_hit_count": time_cap_hits,
        "crawl_cap_pressure_count": cap_pressure_count,
        "crawl_cap_pressure_rate_percent": cap_pressure_rate,
        **async_jobs,
        "last_run_at": _datetime_or_none(row["last_run_at"]) if row else None,
        "max_pages_without_approval": CRAWL_MAX_PAGES_WITHOUT_APPROVAL,
        "max_depth_without_approval": CRAWL_MAX_DEPTH_WITHOUT_APPROVAL,
        "same_host_required": True,
        "forms_allowed": False,
        "credential_entry_allowed": False,
        "raw_web_content_is_untrusted": True,
    }


def _render_quality_watch(
    *,
    render_total: int,
    weak_empty_rate_percent: int,
    missing_screenshot_count: int,
    missing_evidence_count: int,
) -> dict[str, str]:
    if render_total <= 0:
        return {
            "render_quality_watch_status": "observe",
            "render_quality_next_action": "watch_real_approved_render_usage",
            "render_quality_watch_reason": "no_approved_render_runs_in_window",
        }

    missing_count = max(missing_screenshot_count, missing_evidence_count)
    action_needed = render_total >= _RENDER_ACTION_MIN_RUNS and (
        weak_empty_rate_percent >= _RENDER_ACTION_WEAK_EMPTY_RATE_PERCENT
        or missing_count >= _RENDER_ACTION_MISSING_COUNT
    )
    if action_needed:
        return {
            "render_quality_watch_status": "action",
            "render_quality_next_action": "add_render_retry_or_site_tuning",
            "render_quality_watch_reason": "render_quality_signal_above_threshold",
        }
    if weak_empty_rate_percent > 0 or missing_count > 0:
        return {
            "render_quality_watch_status": "watch",
            "render_quality_next_action": "review_latest_render_runs",
            "render_quality_watch_reason": "render_quality_signal_present",
        }
    return {
        "render_quality_watch_status": "observe",
        "render_quality_next_action": "keep_watching_render_rollup",
        "render_quality_watch_reason": "render_quality_clean_in_window",
    }


def _async_crawl_jobs_watch(
    *,
    crawl_request_count: int,
    cap_pressure_count: int,
    cap_pressure_rate_percent: int,
) -> dict[str, str]:
    if crawl_request_count <= 0:
        return {
            "async_crawl_jobs_status": "not_needed",
            "async_crawl_jobs_next_action": "watch_real_map_crawl_usage",
            "async_crawl_jobs_reason": "no_map_or_crawl_runs_in_window",
        }
    action_needed = crawl_request_count >= _CRAWL_CAP_ACTION_MIN_RUNS and (
        cap_pressure_rate_percent >= _CRAWL_CAP_ACTION_RATE_PERCENT
        or cap_pressure_count >= _CRAWL_CAP_ACTION_COUNT
    )
    if action_needed:
        return {
            "async_crawl_jobs_status": "recommended",
            "async_crawl_jobs_next_action": "plan_async_crawl_jobs",
            "async_crawl_jobs_reason": "crawl_cap_pressure_above_threshold",
        }
    if cap_pressure_count > 0:
        return {
            "async_crawl_jobs_status": "watch",
            "async_crawl_jobs_next_action": "watch_cap_pressure_trend",
            "async_crawl_jobs_reason": "crawl_cap_pressure_present",
        }
    return {
        "async_crawl_jobs_status": "not_needed",
        "async_crawl_jobs_next_action": "keep_sync_crawler",
        "async_crawl_jobs_reason": "no_cap_pressure_in_window",
    }


async def _web_cache_metadata(conn) -> dict[str, object]:
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE expires_at > NOW())::INTEGER
                AS active_entry_count,
            COUNT(*) FILTER (WHERE expires_at <= NOW())::INTEGER
                AS expired_entry_count,
            COALESCE(SUM(access_count), 0)::INTEGER AS total_hit_count,
            MAX(last_accessed_at) AS last_hit_at,
            MAX(last_seen_at) AS last_seen_at
        FROM public.alpha_internet_web_cache
        """
    )
    return {
        "mode": "durable_public_web_cache",
        "ttl_hours": 168,
        "active_entry_count": _int_row(row, "active_entry_count") if row else 0,
        "expired_entry_count": _int_row(row, "expired_entry_count") if row else 0,
        "total_hit_count": _int_row(row, "total_hit_count") if row else 0,
        "last_hit_at": _datetime_or_none(row["last_hit_at"]) if row else None,
        "last_seen_at": _datetime_or_none(row["last_seen_at"]) if row else None,
        "raw_user_query_stored": False,
        "raw_web_content_is_untrusted": True,
        "index": "search_terms_gin",
        "rerank": "local_quality_term_rerank",
    }


async def _database_check(conn) -> InternetScoutHealthCheck:
    missing_tables: list[str] = []
    for table in _REQUIRED_TABLES:
        exists = await conn.fetchval("SELECT to_regclass($1)", f"public.{table}")
        if exists is None:
            missing_tables.append(table)

    missing_functions: list[str] = []
    for signature in _REQUIRED_FUNCTIONS:
        exists = await conn.fetchval("SELECT to_regprocedure($1)", signature)
        if exists is None:
            missing_functions.append(signature)

    ok = not missing_tables and not missing_functions
    return InternetScoutHealthCheck(
        ok=ok,
        status="ok" if ok else "unavailable",
        detail="Beacon database contract is present."
        if ok
        else "Beacon database contract is incomplete.",
        metadata={
            "missing_tables": missing_tables,
            "missing_functions": missing_functions,
        },
    )


async def _gateway_check(
    gateway_client: InternetScoutGatewayClient,
) -> InternetScoutHealthCheck:
    try:
        payload = await gateway_client.health()
    except InternetScoutGatewayError as exc:
        return InternetScoutHealthCheck(
            ok=False,
            status="unavailable",
            detail="Gateway Beacon health endpoint is unreachable.",
            metadata={"error": str(exc)},
        )
    usable_count = _int_payload(payload.get("usable_provider_count"))
    configured_count = _int_payload(payload.get("configured_provider_count"))
    status = str(payload.get("status", "degraded"))
    required_count = _int_payload(payload.get("required_provider_count"))
    if required_count <= 0:
        required_count = _min_usable_provider_count()
    redundancy_ok = bool(payload.get("provider_redundancy_ok"))
    if "provider_redundancy_ok" not in payload:
        redundancy_ok = usable_count >= required_count
    has_usable_provider = usable_count > 0
    provider_warning_status = str(payload.get("provider_warning_status") or "")
    backup_budget_guard_warning = (
        status == "warning"
        and provider_warning_status == "backup_budget_capped"
        and has_usable_provider
    )
    ok = (
        status == "ok" and has_usable_provider and redundancy_ok
    ) or backup_budget_guard_warning
    redundancy_status = str(
        payload.get(
            "provider_redundancy_status",
            _provider_redundancy_status(
                usable_provider_count=usable_count,
                required_provider_count=required_count,
            ),
        )
    )
    return InternetScoutHealthCheck(
        ok=ok,
        status="warning" if backup_budget_guard_warning else "ok" if ok else "degraded",
        detail=_gateway_detail(
            usable_provider_count=usable_count,
            required_provider_count=required_count,
            provider_warning_status=provider_warning_status,
        ),
        metadata={
            "gateway_status": status,
            "configured_provider_count": configured_count,
            "usable_provider_count": usable_count,
            "required_provider_count": required_count,
            "provider_redundancy_ok": redundancy_ok,
            "provider_redundancy_status": redundancy_status,
            "provider_warning_status": provider_warning_status or None,
            "missing_provider_count": max(0, required_count - usable_count),
            "provider_order": payload.get("provider_order", []),
            "providers": payload.get("providers", []),
            "primary_provider": payload.get("primary_provider"),
            "primary_provider_usable": payload.get("primary_provider_usable"),
            "budget_capped_provider_count": payload.get(
                "budget_capped_provider_count",
                0,
            ),
            "budget_capped_backup_provider_count": payload.get(
                "budget_capped_backup_provider_count",
                0,
            ),
        },
    )


def _browser_runtime_check() -> InternetScoutHealthCheck:
    payload = browser_runtime_health()
    ok = bool(payload.get("ok"))
    runtime = str(payload.get("runtime", "disabled"))
    return InternetScoutHealthCheck(
        ok=ok,
        status="ok" if ok else "degraded",
        detail="Browser runtime is ready."
        if ok
        else f"Browser runtime is not ready: {runtime}.",
        metadata=payload,
    )


def _min_usable_provider_count() -> int:
    try:
        value = int(os.getenv("BEACON_MIN_USABLE_SEARCH_PROVIDERS", "2"))
    except ValueError:
        return 2
    return min(max(value, 1), 10)


def _provider_redundancy_status(
    *,
    usable_provider_count: int,
    required_provider_count: int,
) -> str:
    if usable_provider_count == 0:
        return "unavailable"
    if usable_provider_count >= required_provider_count:
        return "redundant"
    return "single_provider"


def _gateway_detail(
    *,
    usable_provider_count: int,
    required_provider_count: int,
    provider_warning_status: str = "",
) -> str:
    if usable_provider_count == 0:
        return "Gateway has no usable search provider."
    if provider_warning_status == "backup_budget_capped":
        return (
            "Gateway has "
            f"{usable_provider_count} usable search provider(s); backup provider is "
            "capped by spend guard."
        )
    if usable_provider_count < required_provider_count:
        return (
            "Gateway has "
            f"{usable_provider_count} usable search provider(s); production "
            f"redundancy requires {required_provider_count}."
        )
    return "Gateway has redundant usable search providers."


async def _recent_evidence_check(
    conn, *, checked_at: datetime
) -> InternetScoutHealthCheck:
    if not await _table_exists(conn, "alpha_internet_requests"):
        return InternetScoutHealthCheck(
            ok=False,
            status="unavailable",
            detail="Beacon request table is missing.",
        )
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'succeeded') AS succeeded,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed,
            COUNT(*) FILTER (WHERE status = 'blocked') AS blocked
        FROM public.alpha_internet_requests
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        """
    )
    last_request = await conn.fetchrow(
        """
        SELECT id, requester, selected_tool, status, created_at, updated_at
        FROM public.alpha_internet_requests
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    quality_row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE metadata->>'source_quality_status' = 'insufficient'
            ) AS insufficient_source_quality,
            COUNT(*) FILTER (
                WHERE metadata->>'source_quality_status' = 'weak'
            ) AS weak_source_quality,
            COUNT(*) FILTER (
                WHERE metadata->>'source_quality_status' = 'supported'
            ) AS supported_source_quality,
            COALESCE(SUM(
                CASE
                    WHEN metadata->>'rejected_citation_count' ~ '^[0-9]+$'
                    THEN (metadata->>'rejected_citation_count')::INTEGER
                    ELSE 0
                END
            ), 0)::INTEGER AS rejected_citation_count,
            COALESCE(SUM(
                CASE
                    WHEN metadata->>'official_source_count' ~ '^[0-9]+$'
                    THEN (metadata->>'official_source_count')::INTEGER
                    ELSE 0
                END
            ), 0)::INTEGER AS official_source_count,
            COALESCE(SUM(
                CASE
                    WHEN metadata->>'prompt_injection_rejection_count' ~ '^[0-9]+$'
                    THEN (metadata->>'prompt_injection_rejection_count')::INTEGER
                    ELSE 0
                END
            ), 0)::INTEGER AS prompt_injection_rejection_count
        FROM public.alpha_internet_tool_events
        WHERE event_type = 'chat_evidence_quality'
          AND status = 'succeeded'
          AND created_at >= NOW() - INTERVAL '24 hours'
        """
    )
    suggestion_row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE internet_metadata ? 'web_suggestion_mode'
            ) AS suggested,
            COUNT(*) FILTER (
                WHERE internet_metadata->>'web_suggestion_confidence' = 'high'
            ) AS high_confidence,
            COUNT(*) FILTER (
                WHERE internet_metadata->>'web_suggestion_confidence' = 'medium'
            ) AS medium_confidence
        FROM public.chat_messages
        WHERE role = 'assistant'
          AND internet_metadata ? 'web_suggestion_mode'
          AND created_at >= NOW() - INTERVAL '24 hours'
        """
    )
    acceptance_row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) AS accepted,
            COUNT(*) FILTER (
                WHERE metadata->>'suggested_mode' = metadata->>'requested_mode'
            ) AS accepted_matching_mode,
            COUNT(*) FILTER (
                WHERE metadata->>'requires_confirmation' = 'true'
            ) AS accepted_after_confirmation
        FROM public.alpha_internet_tool_events
        WHERE event_type = 'chat_web_suggestion_acceptance'
          AND status = 'succeeded'
          AND created_at >= NOW() - INTERVAL '24 hours'
        """
    )
    latency_row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE status IN ('succeeded', 'failed', 'blocked')
                  AND updated_at IS NOT NULL
                  AND updated_at >= created_at
            )::INTEGER AS sample_count,
            COALESCE(ROUND(AVG(
                EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000
            ))::INTEGER, 0) AS avg_ms,
            COALESCE(ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000
            ))::INTEGER, 0) AS p95_ms,
            COALESCE(ROUND(MAX(
                EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000
            ))::INTEGER, 0) AS max_ms,
            COUNT(*) FILTER (
                WHERE status IN ('succeeded', 'failed', 'blocked')
                  AND updated_at IS NOT NULL
                  AND updated_at >= created_at
                  AND EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000 > $1
            )::INTEGER AS slow_request_count
        FROM public.alpha_internet_requests
        WHERE created_at >= NOW() - INTERVAL '24 hours'
          AND status IN ('succeeded', 'failed', 'blocked')
          AND updated_at IS NOT NULL
          AND updated_at >= created_at
        """,
        _answer_latency_slo_ms(),
    )
    quality_canary_rows = await conn.fetch(
        """
        SELECT request_id, status, metadata, created_at
        FROM public.alpha_internet_tool_events
        WHERE event_type = 'quality_canary'
        ORDER BY created_at DESC
        LIMIT 7
        """
    )
    quality_canary_history = [
        _quality_canary_summary(row, checked_at=checked_at)
        for row in quality_canary_rows[:_QUALITY_CANARY_HISTORY_LIMIT]
    ]
    quality_canary_trend = _quality_canary_trend(
        quality_canary_rows[:_QUALITY_CANARY_HISTORY_LIMIT],
    )
    quality_canary = _quality_canary_metadata(
        quality_canary_rows[0] if quality_canary_rows else None,
        checked_at=checked_at,
    )
    total = int(row["total"] or 0) if row else 0
    failed = int(row["failed"] or 0) if row else 0
    ok = failed == 0
    return InternetScoutHealthCheck(
        ok=ok,
        status="ok" if ok else "degraded",
        detail="No recent Beacon request failures."
        if ok
        else "Recent Beacon request failures are present.",
        metadata={
            "window_hours": 24,
            "total": total,
            "succeeded": int(row["succeeded"] or 0) if row else 0,
            "failed": failed,
            "blocked": int(row["blocked"] or 0) if row else 0,
            "last_request": _last_request_metadata(last_request),
            "source_quality": _quality_metadata(quality_row),
            "latency": _latency_metadata(latency_row),
            "web_suggestion": _web_suggestion_metadata(
                suggestion_row,
                acceptance_row,
            ),
            "quality_canary": quality_canary,
            "quality_canary_history": quality_canary_history,
            "quality_canary_trend": quality_canary_trend,
        },
    )


async def _table_exists(conn, table: str) -> bool:
    value = await conn.fetchval("SELECT to_regclass($1)", f"public.{table}")
    return value is not None


def _int_payload(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _last_request_metadata(row: _RequestRow | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "requester": str(row["requester"]),
        "selected_tool": str(row["selected_tool"]),
        "status": str(row["status"]),
        "created_at": _datetime_metadata(row["created_at"]),
        "updated_at": _datetime_metadata(row["updated_at"]),
    }


def _quality_metadata(row: _RequestRow | None) -> dict[str, object]:
    if row is None:
        return {
            "supported": 0,
            "weak": 0,
            "insufficient": 0,
            "rejected_citation_count": 0,
            "official_source_count": 0,
            "prompt_injection_rejection_count": 0,
        }
    return {
        "supported": _int_row(row, "supported_source_quality"),
        "weak": _int_row(row, "weak_source_quality"),
        "insufficient": _int_row(row, "insufficient_source_quality"),
        "rejected_citation_count": _int_row(row, "rejected_citation_count"),
        "official_source_count": _int_row(row, "official_source_count"),
        "prompt_injection_rejection_count": _int_row(
            row,
            "prompt_injection_rejection_count",
        ),
    }


def _latency_metadata(row: _RequestRow | None) -> dict[str, object]:
    target_ms = _answer_latency_slo_ms()
    if row is None:
        return _empty_latency_metadata(target_ms)
    sample_count = _safe_int_row(row, "sample_count")
    slow_request_count = _safe_int_row(row, "slow_request_count")
    met_count = max(sample_count - slow_request_count, 0)
    return {
        "window_hours": 24,
        "sample_count": sample_count,
        "avg_ms": _safe_int_row(row, "avg_ms"),
        "p95_ms": _safe_int_row(row, "p95_ms"),
        "max_ms": _safe_int_row(row, "max_ms"),
        "slo_target_ms": target_ms,
        "slow_request_count": slow_request_count,
        "slo_met_percent": round((met_count / sample_count) * 100)
        if sample_count
        else 0,
    }


def _empty_latency_metadata(target_ms: int) -> dict[str, object]:
    return {
        "window_hours": 24,
        "sample_count": 0,
        "avg_ms": 0,
        "p95_ms": 0,
        "max_ms": 0,
        "slo_target_ms": target_ms,
        "slow_request_count": 0,
        "slo_met_percent": 0,
    }


def _web_suggestion_metadata(
    suggestion_row: _RequestRow | None,
    acceptance_row: _RequestRow | None,
) -> dict[str, object]:
    suggested = _int_row(suggestion_row, "suggested") if suggestion_row else 0
    accepted = _int_row(acceptance_row, "accepted") if acceptance_row else 0
    acceptance_rate_percent = round((accepted / suggested) * 100) if suggested else 0
    return {
        "suggested": suggested,
        "accepted": accepted,
        "acceptance_rate_percent": acceptance_rate_percent,
        "high_confidence": _int_row(suggestion_row, "high_confidence")
        if suggestion_row
        else 0,
        "medium_confidence": _int_row(suggestion_row, "medium_confidence")
        if suggestion_row
        else 0,
        "accepted_matching_mode": _int_row(acceptance_row, "accepted_matching_mode")
        if acceptance_row
        else 0,
        "accepted_after_confirmation": _int_row(
            acceptance_row,
            "accepted_after_confirmation",
        )
        if acceptance_row
        else 0,
    }


def _quality_canary_check(
    recent_evidence_metadata: dict[str, object],
) -> InternetScoutHealthCheck:
    quality_canary = recent_evidence_metadata.get("quality_canary")
    if not isinstance(quality_canary, dict):
        return InternetScoutHealthCheck(
            ok=False,
            status="degraded",
            detail="Beacon quality canary has not run.",
            metadata={
                "alert_status": "missing",
                "alert_reason": "quality_canary_missing",
            },
        )

    alert = quality_canary.get("alert")
    alert_payload = alert if isinstance(alert, dict) else {}
    alert_status = str(alert_payload.get("status") or "missing")
    ok = alert_status == "ok"
    detail = (
        "Beacon quality canary is fresh and passing."
        if ok
        else str(alert_payload.get("reason") or "Beacon quality canary needs review.")
    )
    return InternetScoutHealthCheck(
        ok=ok,
        status="ok" if ok else "degraded",
        detail=detail,
        metadata={
            "alert_status": alert_status,
            "alert_reason": str(alert_payload.get("reason") or ""),
            "quality_canary": quality_canary,
            "history": recent_evidence_metadata.get("quality_canary_history", []),
            "trend": recent_evidence_metadata.get("quality_canary_trend", {}),
        },
    )


def _quality_canary_metadata(
    row: _RequestRow | None,
    *,
    checked_at: datetime,
) -> dict[str, object] | None:
    if row is None:
        return None
    summary = _quality_canary_summary(row, checked_at=checked_at)
    summary["alert"] = _quality_canary_alert(summary)
    return summary


def _quality_canary_summary(
    row: _RequestRow,
    *,
    checked_at: datetime,
) -> dict[str, object]:
    metadata = _metadata_object(row["metadata"])
    created_at = row["created_at"]
    age_hours = _age_hours(created_at, checked_at=checked_at)
    expected_interval_hours = _quality_canary_expected_interval_hours()
    next_due_at = (
        _datetime_metadata(created_at + timedelta(hours=expected_interval_hours))
        if isinstance(created_at, datetime)
        else None
    )
    return {
        "request_id": str(metadata.get("request_id") or row["request_id"]),
        "status": str(metadata.get("status") or row["status"]),
        "suite": str(metadata.get("suite") or "beacon_search_quality"),
        "suite_version": _int_mapping(metadata, "suite_version"),
        "case_count": _int_mapping(metadata, "case_count"),
        "passed": _int_mapping(metadata, "passed"),
        "failed": _int_mapping(metadata, "failed"),
        "failure_names": _str_list(metadata.get("failure_names")),
        "case_groups": _quality_canary_case_groups(metadata.get("case_groups")),
        "last_run_at": _datetime_metadata(created_at),
        "age_hours": age_hours,
        "expected_interval_hours": expected_interval_hours,
        "next_due_at": next_due_at,
        "schedule_status": _quality_canary_schedule_status(
            age_hours=age_hours,
            expected_interval_hours=expected_interval_hours,
        ),
        "stale_after_hours": _quality_canary_stale_after_hours(),
    }


def _quality_canary_alert(summary: dict[str, object]) -> dict[str, object]:
    status = str(summary.get("status") or "unknown")
    age_hours = _int_mapping(summary, "age_hours")
    stale_after_hours = _int_mapping(summary, "stale_after_hours")
    failed = _int_mapping(summary, "failed")
    case_count = _int_mapping(summary, "case_count")
    passed = _int_mapping(summary, "passed")
    if status != "passed" or failed > 0:
        return {
            "status": "failed",
            "reason": "quality_canary_failed",
            "severity": "warning",
        }
    if case_count and passed < case_count:
        return {
            "status": "failed",
            "reason": "quality_canary_incomplete",
            "severity": "warning",
        }
    if age_hours > stale_after_hours:
        return {
            "status": "stale",
            "reason": "quality_canary_stale",
            "severity": "warning",
        }
    return {
        "status": "ok",
        "reason": "quality_canary_fresh",
        "severity": "info",
    }


def _quality_canary_trend(rows: list[_RequestRow]) -> dict[str, object]:
    if not rows:
        return {
            "window_runs": 0,
            "passed_runs": 0,
            "failed_runs": 0,
            "pass_rate_percent": 0,
            "trend": "unknown",
        }
    summaries = [_quality_canary_trend_summary(row) for row in rows]
    latest = summaries[0]
    oldest = summaries[-1]
    failed_runs = sum(1 for item in summaries if _quality_canary_trend_failed(item))
    passed_runs = len(summaries) - failed_runs
    latest_reporting = _answer_reporting(rows[0])
    oldest_reporting = _answer_reporting(rows[-1])
    return {
        "window_runs": len(summaries),
        "passed_runs": passed_runs,
        "failed_runs": failed_runs,
        "pass_rate_percent": round((passed_runs / len(summaries)) * 100),
        "latest_failed": _int_mapping(latest, "failed"),
        "failed_delta": _int_mapping(latest, "failed") - _int_mapping(oldest, "failed"),
        "passed_delta": _int_mapping(latest, "passed") - _int_mapping(oldest, "passed"),
        "case_count_delta": _int_mapping(latest, "case_count")
        - _int_mapping(oldest, "case_count"),
        "latest_precision": _nested_float(
            latest_reporting,
            ("citation_precision", "precision"),
        ),
        "precision_delta": round(
            _nested_float(latest_reporting, ("citation_precision", "precision"))
            - _nested_float(oldest_reporting, ("citation_precision", "precision")),
            4,
        ),
        "latest_suite_elapsed_ms": _nested_int(
            latest_reporting,
            ("latency", "suite_elapsed_ms"),
        ),
        "latency_delta_ms": _nested_int(
            latest_reporting,
            ("latency", "suite_elapsed_ms"),
        )
        - _nested_int(oldest_reporting, ("latency", "suite_elapsed_ms")),
        "estimated_provider_cost_usd": _nested_float(
            latest_reporting,
            ("cost", "estimated_provider_cost_usd"),
        ),
        "trend": _quality_canary_trend_label(
            latest_failed=_quality_canary_trend_failed(latest),
            oldest_failed=_quality_canary_trend_failed(oldest),
            failed_runs=failed_runs,
            run_count=len(summaries),
        ),
    }


def _quality_canary_trend_summary(row: _RequestRow) -> dict[str, object]:
    metadata = _metadata_object(row["metadata"])
    return {
        "status": str(metadata.get("status") or "unknown"),
        "case_count": _int_mapping(metadata, "case_count"),
        "passed": _int_mapping(metadata, "passed"),
        "failed": _int_mapping(metadata, "failed"),
    }


def _quality_canary_trend_failed(summary: dict[str, object]) -> bool:
    return str(summary.get("status") or "unknown") != "passed" or (
        _int_mapping(summary, "failed") > 0
    )


def _quality_canary_trend_label(
    *,
    latest_failed: bool,
    oldest_failed: bool,
    failed_runs: int,
    run_count: int,
) -> str:
    if run_count < 2:
        return "single_sample"
    if latest_failed and not oldest_failed:
        return "regressing"
    if oldest_failed and not latest_failed:
        return "improving"
    if failed_runs:
        return "stable_with_failures"
    return "stable"


def _answer_reporting(row: _RequestRow) -> dict[str, object]:
    metadata = _metadata_object(row["metadata"])
    answer_engine = metadata.get("answer_engine")
    if not isinstance(answer_engine, dict):
        return {}
    reporting = answer_engine.get("reporting")
    return reporting if isinstance(reporting, dict) else {}


def _age_hours(value: object, *, checked_at: datetime) -> int:
    if not isinstance(value, datetime):
        return 0
    created_at = value
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return max(0, int((checked_at - created_at).total_seconds() // 3600))


def _quality_canary_stale_after_hours() -> int:
    raw_value = os.getenv(
        "BEACON_QUALITY_CANARY_STALE_AFTER_HOURS",
        str(_QUALITY_CANARY_STALE_AFTER_HOURS),
    )
    try:
        value = int(raw_value)
    except ValueError:
        return _QUALITY_CANARY_STALE_AFTER_HOURS
    return max(1, min(value, 168))


def _quality_canary_expected_interval_hours() -> int:
    raw_value = os.getenv("BEACON_QUALITY_CANARY_EXPECTED_INTERVAL_HOURS", "24")
    try:
        value = int(raw_value)
    except ValueError:
        return 24
    return max(1, min(value, 168))


def _quality_canary_schedule_status(
    *,
    age_hours: int,
    expected_interval_hours: int,
) -> str:
    if age_hours > _quality_canary_stale_after_hours():
        return "stale"
    if age_hours >= expected_interval_hours:
        return "due"
    return "ok"


def _metadata_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _int_row(row: _RequestRow, key: str) -> int:
    value = row[key]
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _safe_int_row(row: _RequestRow, key: str) -> int:
    try:
        return _int_row(row, key)
    except (KeyError, TypeError):
        return 0


def _answer_latency_slo_ms() -> int:
    try:
        value = int(os.getenv("BEACON_ANSWER_LATENCY_SLO_MS", ""))
    except ValueError:
        return _DEFAULT_ANSWER_LATENCY_SLO_MS
    return min(max(value, 1_000), 120_000)


def _int_mapping(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _nested_mapping(payload: dict[str, object], path: tuple[str, ...]) -> object:
    current: object = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _nested_int(payload: dict[str, object], path: tuple[str, ...]) -> int:
    value = _nested_mapping(payload, path)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _nested_float(payload: dict[str, object], path: tuple[str, ...]) -> float:
    value = _nested_mapping(payload, path)
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:20]]


def _quality_canary_case_groups(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}

    groups: dict[str, dict[str, object]] = {}
    for raw_name, raw_group in sorted(value.items()):
        if not isinstance(raw_group, dict):
            continue
        name = str(raw_name)
        if not name:
            continue
        groups[name] = {
            "case_count": _int_mapping(raw_group, "case_count"),
            "passed": _int_mapping(raw_group, "passed"),
            "failed": _int_mapping(raw_group, "failed"),
            "failure_names": _str_list(raw_group.get("failure_names")),
            "case_names": _str_list(raw_group.get("case_names")),
        }
    return groups


def _datetime_or_none(value: object) -> str | None:
    if value is None:
        return None
    return _datetime_metadata(value)


def _datetime_metadata(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
