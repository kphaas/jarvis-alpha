"""Production readiness checks for Beacon internet-scout."""

from __future__ import annotations

from datetime import UTC, datetime
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
from brain.services.internet_scout.retention import build_retention_report

_REQUIRED_TABLES = (
    "alpha_internet_requests",
    "alpha_internet_sources",
    "alpha_internet_evidence",
    "alpha_internet_tool_events",
    "alpha_internet_memory_promotions",
)
_REQUIRED_FUNCTIONS = ("public.save_beacon_semantic_memory(uuid,text,text,text,text)",)
_READINESS_CHECKS = (
    "database",
    "gateway",
    "browser_runtime",
    "retention",
    "quality_canary",
)
_QUALITY_CANARY_HISTORY_LIMIT = 7
_QUALITY_CANARY_STALE_AFTER_HOURS = 26


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
    redundancy_ok = usable_count >= required_count
    has_usable_provider = usable_count > 0
    ok = status == "ok" and has_usable_provider and redundancy_ok
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
        status="ok" if ok else "degraded",
        detail=_gateway_detail(
            usable_provider_count=usable_count,
            required_provider_count=required_count,
        ),
        metadata={
            "gateway_status": status,
            "configured_provider_count": configured_count,
            "usable_provider_count": usable_count,
            "required_provider_count": required_count,
            "provider_redundancy_ok": redundancy_ok,
            "provider_redundancy_status": redundancy_status,
            "missing_provider_count": max(0, required_count - usable_count),
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
) -> str:
    if usable_provider_count == 0:
        return "Gateway has no usable search provider."
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
            "web_suggestion": _web_suggestion_metadata(
                suggestion_row,
                acceptance_row,
            ),
            "quality_canary": quality_canary,
            "quality_canary_history": quality_canary_history,
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


def _int_mapping(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


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


def _datetime_metadata(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
