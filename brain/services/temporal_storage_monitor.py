from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timezone
from typing import Any

import asyncpg

from jarvis_common.logging_config import get_logger

log = get_logger("alpha_temporal_storage")

TEMPORAL_DATABASES = (
    ("temporal", "history_node"),
    ("temporal_visibility", "executions_visibility"),
)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("invalid integer env var %s=%r; using %s", name, raw, default)
        return default


def _alert_free_fraction() -> float:
    raw = os.getenv("TEMPORAL_STORAGE_ALERT_FREE_FRACTION", "0.75")
    try:
        fraction = float(raw)
    except ValueError:
        log.warning("invalid TEMPORAL_STORAGE_ALERT_FREE_FRACTION=%r; using 0.75", raw)
        return 0.75
    if fraction <= 0 or fraction > 1:
        log.warning(
            "TEMPORAL_STORAGE_ALERT_FREE_FRACTION out of range: %r; using 0.75", raw
        )
        return 0.75
    return fraction


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def _quote_ident(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"unsafe identifier: {identifier!r}")
    return f'"{identifier}"'


def _status_for_snapshot(*, errors: list[str], threshold_exceeded: bool) -> str:
    if threshold_exceeded:
        return "alert"
    if errors:
        return "degraded"
    return "ok"


def _build_snapshot_payload(
    *,
    checked_at: datetime,
    disk_path: str,
    disk_total_bytes: int,
    disk_free_bytes: int,
    databases: list[dict[str, Any]],
    errors: list[str],
    alert_free_fraction: float,
) -> dict[str, Any]:
    temporal_total_bytes = sum(
        int(db["size_bytes"])
        for db in databases
        if isinstance(db.get("size_bytes"), int)
    )
    threshold_bytes = int(disk_free_bytes * alert_free_fraction)
    threshold_exceeded = threshold_bytes > 0 and temporal_total_bytes >= threshold_bytes
    status = _status_for_snapshot(
        errors=errors,
        threshold_exceeded=threshold_exceeded,
    )
    return {
        "status": status,
        "checked_at": checked_at.isoformat(),
        "disk_path": disk_path,
        "disk_total_bytes": disk_total_bytes,
        "disk_total_pretty": _format_bytes(disk_total_bytes),
        "disk_free_bytes": disk_free_bytes,
        "disk_free_pretty": _format_bytes(disk_free_bytes),
        "alert_free_fraction": alert_free_fraction,
        "threshold_bytes": threshold_bytes,
        "threshold_pretty": _format_bytes(threshold_bytes),
        "threshold_exceeded": threshold_exceeded,
        "temporal_total_bytes": temporal_total_bytes,
        "temporal_total_pretty": _format_bytes(temporal_total_bytes),
        "databases": databases,
        "errors": errors,
    }


async def _collect_temporal_database(
    database: str, row_count_table: str, *, include_row_counts: bool
) -> dict[str, Any]:
    password = os.getenv("TEMPORAL_DB_PASSWORD")
    row_counts: dict[str, int | None] = {row_count_table: None}
    if not password:
        return {
            "name": database,
            "size_bytes": None,
            "size_pretty": "unknown",
            "row_counts": row_counts,
            "error": "TEMPORAL_DB_PASSWORD not set",
        }

    host = os.getenv("TEMPORAL_DB_HOST", "localhost")
    port = _env_int("TEMPORAL_DB_PORT", 5432)
    user = os.getenv("TEMPORAL_DB_USER", "temporal")
    timeout = float(os.getenv("TEMPORAL_STORAGE_QUERY_TIMEOUT_SECONDS", "5"))

    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            timeout=timeout,
        )
        size_bytes = await conn.fetchval("SELECT pg_database_size(current_database())")
        if include_row_counts:
            row_count = await conn.fetchval(
                f"SELECT count(*) FROM {_quote_ident(row_count_table)}"
            )
            row_counts[row_count_table] = int(row_count)
        return {
            "name": database,
            "size_bytes": int(size_bytes),
            "size_pretty": _format_bytes(int(size_bytes)),
            "row_counts": row_counts,
            "error": None,
        }
    except Exception as exc:
        log.warning("temporal storage query failed for %s: %s", database, exc)
        return {
            "name": database,
            "size_bytes": None,
            "size_pretty": "unknown",
            "row_counts": row_counts,
            "error": str(exc),
        }
    finally:
        if conn is not None:
            await conn.close()


async def collect_temporal_storage_snapshot(
    *, include_row_counts: bool = False
) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc)
    disk_path = os.getenv("TEMPORAL_STORAGE_DISK_PATH", "/")
    try:
        usage = shutil.disk_usage(disk_path)
    except OSError as exc:
        log.warning("disk usage failed for %s: %s; falling back to /", disk_path, exc)
        disk_path = "/"
        usage = shutil.disk_usage(disk_path)

    results = await asyncio.gather(
        *(
            _collect_temporal_database(
                database,
                table,
                include_row_counts=include_row_counts,
            )
            for database, table in TEMPORAL_DATABASES
        ),
        return_exceptions=True,
    )

    databases: list[dict[str, Any]] = []
    errors: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            msg = str(result)
            errors.append(msg)
            continue
        databases.append(result)
        if result.get("error"):
            errors.append(f"{result['name']}: {result['error']}")

    return _build_snapshot_payload(
        checked_at=checked_at,
        disk_path=disk_path,
        disk_total_bytes=usage.total,
        disk_free_bytes=usage.free,
        databases=databases,
        errors=errors,
        alert_free_fraction=_alert_free_fraction(),
    )


def temporal_storage_summary_body(snapshot: dict[str, Any]) -> str:
    parts = [
        f"Temporal total {snapshot['temporal_total_pretty']}",
        f"free disk {snapshot['disk_free_pretty']}",
        f"alert threshold {snapshot['threshold_pretty']}",
    ]
    rows = []
    for db in snapshot.get("databases", []):
        row_bits = []
        for table, count in (db.get("row_counts") or {}).items():
            row_bits.append(f"{table}={count if count is not None else 'unknown'}")
        row_text = ", ".join(row_bits) if row_bits else "rows=unknown"
        rows.append(f"{db.get('name')}: {db.get('size_pretty')} ({row_text})")
    if rows:
        parts.append("; ".join(rows))
    if snapshot.get("errors"):
        parts.append("errors: " + "; ".join(snapshot["errors"]))
    return ". ".join(parts) + "."
