"""Read-only temporal intelligence helpers for memory graph rows.

The helpers accept sanitized graph row dictionaries from API/DB callers and
return aggregate metadata only. They do not inspect raw memories or write rows.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable


GraphRow = dict[str, Any]


def summarize_temporal_graph_rows(
    *,
    nodes: Iterable[GraphRow],
    edges: Iterable[GraphRow],
    now: datetime | None = None,
    stale_after_days: int = 90,
    recent_days: int = 14,
) -> dict[str, Any]:
    """Summarize time-sensitive graph state without exposing row content."""

    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
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
