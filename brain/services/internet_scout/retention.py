"""Retention inventory and reviewed cleanup controls for Beacon evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from uuid import UUID

from brain.services.internet_scout.models import (
    InternetScoutRetentionDeleteRequest,
    InternetScoutRetentionDeleteResponse,
    InternetScoutRetentionReport,
)

_DEFAULT_EVIDENCE_RETENTION_DAYS = 90
_DEFAULT_SCREENSHOT_RETENTION_DAYS = 30
_RETENTION_DELETE_ENABLED_ENV = "BEACON_RETENTION_DELETE_ENABLED"


async def build_retention_report(conn) -> InternetScoutRetentionReport:
    """Count retention candidates without deleting or mutating evidence."""
    evidence_days = _bounded_int_env(
        "BEACON_EVIDENCE_RETENTION_DAYS",
        default=_DEFAULT_EVIDENCE_RETENTION_DAYS,
        minimum=7,
        maximum=3650,
    )
    screenshot_days = _bounded_int_env(
        "BEACON_BROWSER_SCREENSHOT_RETENTION_DAYS",
        default=_DEFAULT_SCREENSHOT_RETENTION_DAYS,
        minimum=1,
        maximum=3650,
    )
    screenshot_count, screenshot_bytes = _screenshot_retention_inventory(
        retention_days=screenshot_days,
    )
    return InternetScoutRetentionReport(
        evidence_retention_days=evidence_days,
        screenshot_retention_days=screenshot_days,
        old_request_count=await _old_row_count(
            conn,
            table="alpha_internet_requests",
            created_column="created_at",
            retention_days=evidence_days,
        ),
        old_source_count=await _old_row_count(
            conn,
            table="alpha_internet_sources",
            created_column="created_at",
            retention_days=evidence_days,
        ),
        old_evidence_count=await _old_row_count(
            conn,
            table="alpha_internet_evidence",
            created_column="created_at",
            retention_days=evidence_days,
        ),
        old_event_count=await _old_row_count(
            conn,
            table="alpha_internet_tool_events",
            created_column="created_at",
            retention_days=evidence_days,
        ),
        old_memory_promotion_count=await _old_row_count(
            conn,
            table="alpha_internet_memory_promotions",
            created_column="created_at",
            retention_days=evidence_days,
        ),
        screenshot_file_count=screenshot_count,
        screenshot_bytes=screenshot_bytes,
    )


async def delete_expired_evidence(
    conn,
    request: InternetScoutRetentionDeleteRequest,
) -> InternetScoutRetentionDeleteResponse:
    """Delete expired Beacon evidence only when reviewed controls are enabled."""
    evidence_days = _bounded_int_env(
        "BEACON_EVIDENCE_RETENTION_DAYS",
        default=_DEFAULT_EVIDENCE_RETENTION_DAYS,
        minimum=7,
        maximum=3650,
    )
    screenshot_days = _bounded_int_env(
        "BEACON_BROWSER_SCREENSHOT_RETENTION_DAYS",
        default=_DEFAULT_SCREENSHOT_RETENTION_DAYS,
        minimum=1,
        maximum=3650,
    )
    screenshot_count, screenshot_bytes = _screenshot_retention_inventory(
        retention_days=screenshot_days,
    )
    request_ids = await _expired_request_ids(
        conn,
        retention_days=evidence_days,
        max_rows=request.max_request_rows,
    )
    enabled = _retention_delete_enabled()
    dry_run = request.dry_run or not enabled
    mode = (
        "dry_run" if dry_run and enabled else "disabled" if not enabled else "deleted"
    )
    response = InternetScoutRetentionDeleteResponse(
        mode=mode,
        enabled=enabled,
        dry_run=dry_run,
        evidence_retention_days=evidence_days,
        screenshot_retention_days=screenshot_days,
        candidate_request_count=len(request_ids),
        candidate_screenshot_file_count=screenshot_count
        if request.include_screenshots
        else 0,
        candidate_screenshot_bytes=screenshot_bytes
        if request.include_screenshots
        else 0,
    )
    if dry_run or not request_ids:
        return response

    await conn.execute(
        "SELECT set_config('app.beacon_retention_cleanup', 'true', true)"
    )
    response.deleted_memory_promotion_count = await _delete_request_children(
        conn,
        table="alpha_internet_memory_promotions",
        request_ids=request_ids,
    )
    response.deleted_evidence_count = await _delete_request_children(
        conn,
        table="alpha_internet_evidence",
        request_ids=request_ids,
    )
    response.deleted_source_count = await _delete_request_children(
        conn,
        table="alpha_internet_sources",
        request_ids=request_ids,
    )
    response.deleted_event_count = await _delete_request_children(
        conn,
        table="alpha_internet_tool_events",
        request_ids=request_ids,
    )
    response.deleted_request_count = await _delete_requests(conn, request_ids)
    if request.include_screenshots:
        deleted_screenshots, deleted_bytes = _delete_expired_screenshots(
            retention_days=screenshot_days
        )
        response.deleted_screenshot_file_count = deleted_screenshots
        response.deleted_screenshot_bytes = deleted_bytes
    return response


async def _expired_request_ids(
    conn,
    *,
    retention_days: int,
    max_rows: int,
) -> list[UUID]:
    if not await _table_exists(conn, "alpha_internet_requests"):
        return []
    rows = await conn.fetch(
        """
        SELECT id
        FROM public.alpha_internet_requests
        WHERE created_at < NOW() - ($1::int * INTERVAL '1 day')
        ORDER BY created_at ASC
        LIMIT $2
        """,
        retention_days,
        max_rows,
    )
    return [row["id"] for row in rows]


async def _delete_request_children(
    conn,
    *,
    table: str,
    request_ids: list[UUID],
) -> int:
    if not await _table_exists(conn, table):
        return 0
    result = await conn.execute(
        f"""
        DELETE FROM public.{table}
        WHERE request_id = ANY($1::uuid[])
        """,
        request_ids,
    )
    return _command_count(result)


async def _delete_requests(conn, request_ids: list[UUID]) -> int:
    result = await conn.execute(
        """
        DELETE FROM public.alpha_internet_requests
        WHERE id = ANY($1::uuid[])
        """,
        request_ids,
    )
    return _command_count(result)


async def _old_row_count(
    conn,
    *,
    table: str,
    created_column: str,
    retention_days: int,
) -> int:
    if not await _table_exists(conn, table):
        return 0
    value = await conn.fetchval(
        f"""
        SELECT COUNT(*)
        FROM public.{table}
        WHERE {created_column} < NOW() - ($1::int * INTERVAL '1 day')
        """,
        retention_days,
    )
    return int(value or 0)


async def _table_exists(conn, table: str) -> bool:
    value = await conn.fetchval("SELECT to_regclass($1)", f"public.{table}")
    return value is not None


def _screenshot_retention_inventory(*, retention_days: int) -> tuple[int, int]:
    root_value = os.getenv("BEACON_BROWSER_SCREENSHOT_DIR", "").strip()
    if not root_value:
        return 0, 0
    root = Path(root_value)
    if not root.exists() or not root.is_dir():
        return 0, 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    count = 0
    total_bytes = 0
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        if modified_at >= cutoff:
            continue
        count += 1
        total_bytes += stat.st_size
    return count, total_bytes


def _delete_expired_screenshots(*, retention_days: int) -> tuple[int, int]:
    root_value = os.getenv("BEACON_BROWSER_SCREENSHOT_DIR", "").strip()
    if not root_value:
        return 0, 0
    root = Path(root_value)
    if not root.exists() or not root.is_dir():
        return 0, 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    count = 0
    total_bytes = 0
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        try:
            stat = path.stat()
            modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            if modified_at >= cutoff:
                continue
            size = stat.st_size
            path.unlink()
        except OSError:
            continue
        count += 1
        total_bytes += size
    return count, total_bytes


def _retention_delete_enabled() -> bool:
    return os.getenv(_RETENTION_DELETE_ENABLED_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _command_count(result: object) -> int:
    if not isinstance(result, str):
        return 0
    try:
        return int(result.rsplit(" ", 1)[-1])
    except ValueError:
        return 0


def _bounded_int_env(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return min(max(parsed, minimum), maximum)
