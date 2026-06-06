"""Production readiness checks for Beacon internet-scout."""

from __future__ import annotations

from datetime import UTC, datetime

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
    return InternetScoutHealthResponse(
        status="ok" if all(check.ok for check in checks.values()) else "degraded",
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
