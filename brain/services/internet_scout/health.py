"""Production readiness checks for Beacon internet-scout."""

from __future__ import annotations

from datetime import UTC, datetime
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
from brain.services.internet_scout.retention import build_retention_report

_REQUIRED_TABLES = (
    "alpha_internet_requests",
    "alpha_internet_sources",
    "alpha_internet_evidence",
    "alpha_internet_tool_events",
    "alpha_internet_memory_promotions",
)
_REQUIRED_FUNCTIONS = ("public.save_beacon_semantic_memory(uuid,text,text,text,text)",)
_READINESS_CHECKS = ("database", "gateway", "browser_runtime", "retention")


class _RequestRow(Protocol):
    def __getitem__(self, key: str) -> object: ...


async def build_beacon_health(
    conn,
    *,
    gateway_client: InternetScoutGatewayClient | None = None,
) -> InternetScoutHealthResponse:
    checks = {
        "database": await _database_check(conn),
        "gateway": await _gateway_check(gateway_client or InternetScoutGatewayClient()),
        "browser_runtime": _browser_runtime_check(),
        "recent_evidence": await _recent_evidence_check(conn),
    }
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
        checked_at=datetime.now(UTC),
    )


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
    ok = status == "ok" and usable_count > 0
    return InternetScoutHealthCheck(
        ok=ok,
        status="ok" if ok else "degraded",
        detail="Gateway has a usable search provider."
        if ok
        else "Gateway has no usable search provider.",
        metadata={
            "gateway_status": status,
            "configured_provider_count": configured_count,
            "usable_provider_count": usable_count,
            "provider_order": payload.get("provider_order", []),
            "providers": payload.get("providers", []),
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


async def _recent_evidence_check(conn) -> InternetScoutHealthCheck:
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
            "web_suggestion": _web_suggestion_metadata(
                suggestion_row,
                acceptance_row,
            ),
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


def _int_row(row: _RequestRow, key: str) -> int:
    value = row[key]
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _datetime_metadata(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
