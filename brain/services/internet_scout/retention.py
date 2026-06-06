"""Report-only retention inventory for Beacon internet evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path

from brain.services.internet_scout.models import InternetScoutRetentionReport

_DEFAULT_EVIDENCE_RETENTION_DAYS = 90
_DEFAULT_SCREENSHOT_RETENTION_DAYS = 30


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
