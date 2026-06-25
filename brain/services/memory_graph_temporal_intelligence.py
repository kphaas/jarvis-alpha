"""Read-only temporal intelligence helpers for memory graph rows.

The helpers accept sanitized graph row dictionaries from API/DB callers and
return aggregate metadata only. They do not inspect raw memories or write rows.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable


GraphRow = dict[str, Any]
DEFAULT_STALE_AFTER_DAYS = 90


def summarize_temporal_graph_rows(
    *,
    nodes: Iterable[GraphRow],
    edges: Iterable[GraphRow],
    now: datetime | None = None,
    stale_after_days: int = 90,
    recent_days: int = 14,
) -> dict[str, Any]:
    """Summarize time-sensitive graph state without exposing row content."""

    now = _normalize_now(now)
    stale_before = now - timedelta(days=max(1, stale_after_days))
    recent_after = now - timedelta(days=max(1, recent_days))
    node_rows = list(nodes)
    edge_rows = list(edges)

    node_status = [
        _row_status(row, now=now, stale_before=stale_before) for row in node_rows
    ]
    edge_status = [
        _row_status(row, now=now, stale_before=stale_before) for row in edge_rows
    ]
    recent_changes = sum(
        1
        for row in [*node_rows, *edge_rows]
        if (change_at := _change_at(row)) is not None and change_at >= recent_after
    )

    return {
        "active_nodes": node_status.count("active"),
        "active_edges": edge_status.count("active"),
        "expired_nodes": node_status.count("expired"),
        "expired_edges": edge_status.count("expired"),
        "future_nodes": node_status.count("future"),
        "future_edges": edge_status.count("future"),
        "stale_nodes": node_status.count("stale"),
        "stale_edges": edge_status.count("stale"),
        "recent_changes": recent_changes,
        "superseded_node_candidates": _superseded_node_candidates(node_rows),
        "superseded_edge_candidates": _superseded_edge_candidates(edge_rows),
        "conflict_candidates": _superseded_node_candidates(node_rows)
        + _superseded_edge_candidates(edge_rows),
    }


def classify_temporal_graph_row(
    row: GraphRow,
    *,
    object_type: str,
    now: datetime | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
) -> dict[str, str | None]:
    """Return retrieval metadata for one sanitized graph node or edge row."""

    now = _normalize_now(now)
    properties = (
        row.get("properties") if isinstance(row.get("properties"), dict) else {}
    )
    row_stale_after_days = _positive_int(
        properties.get("refresh_prompt_after_days")
        if isinstance(properties, dict)
        else None,
        fallback=stale_after_days,
    )
    stale_before = now - timedelta(days=max(1, row_stale_after_days))
    temporal_state = _row_status(row, now=now, stale_before=stale_before)
    retrieval_state_by_temporal_state = {
        "active": "current",
        "future": "future",
        "expired": "historical",
        "stale": "needs_refresh",
    }
    refresh_prompt_by_temporal_state = {
        "active": None,
        "future": "not_current_yet",
        "expired": "expired_window",
        "stale": "confirm_still_current",
    }
    conflict_key = _conflict_key(row, object_type=object_type)
    return {
        "temporal_state": temporal_state,
        "retrieval_state": retrieval_state_by_temporal_state[temporal_state],
        "refresh_prompt": refresh_prompt_by_temporal_state[temporal_state],
        "conflict_key": conflict_key,
    }


def _row_status(
    row: GraphRow,
    *,
    now: datetime,
    stale_before: datetime,
) -> str:
    valid_from = _parse_datetime(row.get("valid_from"))
    valid_to = _parse_datetime(row.get("valid_to"))
    activity_at = _activity_at(row)
    if valid_from and valid_from > now:
        return "future"
    if valid_to and valid_to <= now:
        return "expired"
    if activity_at and activity_at < stale_before:
        return "stale"
    return "active"


def _conflict_key(row: GraphRow, *, object_type: str) -> str | None:
    if object_type == "node":
        node_type = str(row.get("node_type") or "").strip().casefold()
        label_key = (
            str(row.get("label_hash") or row.get("label_preview") or "")
            .strip()
            .casefold()
        )
        if node_type and label_key:
            return f"node:{node_type}:{label_key}"
        return None
    if object_type == "edge":
        from_id = str(row.get("from_node_id") or "").strip()
        to_id = str(row.get("to_node_id") or "").strip()
        edge_type = str(row.get("edge_type") or "related_to").strip().casefold()
        if from_id and to_id and edge_type:
            return f"edge:{from_id}:{to_id}:{edge_type}"
    return None


def _superseded_node_candidates(rows: list[GraphRow]) -> int:
    groups: dict[tuple[str, str], list[GraphRow]] = defaultdict(list)
    for row in rows:
        node_type = str(row.get("node_type") or "other")
        label_key = str(
            row.get("label_hash") or row.get("label_preview") or row.get("id") or ""
        )
        groups[(node_type, label_key.casefold())].append(row)
    return sum(max(0, len(group) - 1) for group in groups.values() if len(group) > 1)


def _superseded_edge_candidates(rows: list[GraphRow]) -> int:
    groups: dict[tuple[str, str, str], list[GraphRow]] = defaultdict(list)
    for row in rows:
        groups[
            (
                str(row.get("from_node_id") or ""),
                str(row.get("to_node_id") or ""),
                str(row.get("edge_type") or "related_to"),
            )
        ].append(row)
    return sum(max(0, len(group) - 1) for group in groups.values() if len(group) > 1)


def _activity_at(row: GraphRow) -> datetime | None:
    return (
        _parse_datetime(row.get("updated_at"))
        or _parse_datetime(row.get("created_at"))
        or _parse_datetime(row.get("valid_from"))
        or _parse_datetime(row.get("valid_to"))
    )


def _change_at(row: GraphRow) -> datetime | None:
    return _parse_datetime(row.get("updated_at")) or _parse_datetime(
        row.get("created_at")
    )


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _positive_int(value: object, *, fallback: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback
