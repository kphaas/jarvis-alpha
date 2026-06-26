"""Read-only temporal intelligence helpers for memory graph rows.

The helpers accept sanitized graph row dictionaries from API/DB callers and
return aggregate metadata only. They do not inspect raw memories or write rows.
"""

from __future__ import annotations

import hashlib
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
) -> dict[str, str | bool | None]:
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
    review = _review_workflow(
        row=row,
        properties=properties,
        temporal_state=temporal_state,
        now=now,
        stale_after_days=row_stale_after_days,
    )
    return {
        "temporal_state": temporal_state,
        "retrieval_state": retrieval_state_by_temporal_state[temporal_state],
        "refresh_prompt": refresh_prompt_by_temporal_state[temporal_state],
        "conflict_key": conflict_key,
        **review,
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


def _review_workflow(
    *,
    row: GraphRow,
    properties: dict[Any, Any],
    temporal_state: str,
    now: datetime,
    stale_after_days: int,
) -> dict[str, str | bool | None]:
    currentness_policy = str(properties.get("currentness_policy") or "")
    temporal_kind = str(properties.get("temporal_kind") or "")
    requires_resolution = bool(properties.get("requires_operator_resolution"))
    open_ended = _is_open_ended_current_fact(
        row,
        temporal_kind=temporal_kind,
        currentness_policy=currentness_policy,
    )

    if requires_resolution:
        return {
            "review_action": "resolve_conflict",
            "review_priority": "high",
            "review_reason": "operator_resolution_required",
            "review_due_at": _format_datetime(now),
            "open_ended": open_ended,
        }
    if temporal_state == "future":
        return {
            "review_action": "hold_until_valid",
            "review_priority": "low",
            "review_reason": "valid_window_starts_later",
            "review_due_at": _format_datetime(_parse_datetime(row.get("valid_from"))),
            "open_ended": open_ended,
        }
    if temporal_state == "expired":
        return {
            "review_action": "keep_historical",
            "review_priority": "low",
            "review_reason": "valid_window_expired",
            "review_due_at": None,
            "open_ended": open_ended,
        }
    if temporal_state == "stale":
        return {
            "review_action": "refresh",
            "review_priority": (
                "high"
                if currentness_policy in {"candidate_current", "confirm_current"}
                else "medium"
            ),
            "review_reason": "refresh_window_elapsed",
            "review_due_at": _review_due_at(row, days=stale_after_days),
            "open_ended": open_ended,
        }
    if currentness_policy == "historical_needs_confirmation":
        return {
            "review_action": "confirm_currentness",
            "review_priority": "medium",
            "review_reason": "historical_fact_needs_confirmation",
            "review_due_at": _format_datetime(now),
            "open_ended": open_ended,
        }
    if open_ended:
        return {
            "review_action": "refresh",
            "review_priority": "medium",
            "review_reason": "open_ended_current_fact",
            "review_due_at": _review_due_at(row, days=stale_after_days),
            "open_ended": True,
        }
    return {
        "review_action": "none",
        "review_priority": "none",
        "review_reason": None,
        "review_due_at": None,
        "open_ended": False,
    }


def _is_open_ended_current_fact(
    row: GraphRow,
    *,
    temporal_kind: str,
    currentness_policy: str,
) -> bool:
    if _parse_datetime(row.get("valid_to")) is not None:
        return False
    return temporal_kind in {
        "relationship_state",
        "project_state",
        "planned_event",
        "people_state",
    } or currentness_policy in {"candidate_current", "confirm_current"}


def _review_due_at(row: GraphRow, *, days: int) -> str | None:
    activity_at = _activity_at(row)
    if activity_at is None:
        return None
    return _format_datetime(activity_at + timedelta(days=max(1, days)))


def _conflict_key(row: GraphRow, *, object_type: str) -> str | None:
    semantic_key = _semantic_conflict_key(row, object_type=object_type)
    if semantic_key:
        return semantic_key
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
    groups: dict[str, list[GraphRow]] = defaultdict(list)
    for row in rows:
        groups[_node_group_key(row)].append(row)
    return sum(max(0, len(group) - 1) for group in groups.values() if len(group) > 1)


def _superseded_edge_candidates(rows: list[GraphRow]) -> int:
    groups: dict[str, list[GraphRow]] = defaultdict(list)
    for row in rows:
        groups[_edge_group_key(row)].append(row)
    return sum(max(0, len(group) - 1) for group in groups.values() if len(group) > 1)


def _semantic_conflict_key(row: GraphRow, *, object_type: str) -> str | None:
    properties = row.get("properties") if isinstance(row.get("properties"), dict) else {}
    explicit_key = _clean_key_part(properties.get("conflict_group_key"))
    if explicit_key:
        return f"{object_type}:{explicit_key}"
    entity_keys = _string_list(properties.get("entity_keys"))
    if not entity_keys:
        entity_keys = [_entity_key(value) for value in _string_list(properties.get("relationship_subjects"))]
    if not entity_keys:
        return None
    graph_kind = _clean_key_part(properties.get("graph_kind")) or _clean_key_part(row.get("edge_type")) or "related"
    temporal_kind = _clean_key_part(properties.get("temporal_kind")) or "state"
    subject_key = "|".join(sorted(_canonical_entity_key(key) for key in entity_keys))
    return f"{object_type}:{graph_kind}:{temporal_kind}:{subject_key}"


def _node_group_key(row: GraphRow) -> str:
    semantic_key = _semantic_conflict_key(row, object_type="node")
    if semantic_key:
        return semantic_key
    node_type = str(row.get("node_type") or "other").casefold()
    label_key = str(row.get("label_hash") or row.get("label_preview") or row.get("id") or "")
    return f"node:{node_type}:{label_key.casefold()}"


def _edge_group_key(row: GraphRow) -> str:
    semantic_key = _semantic_conflict_key(row, object_type="edge")
    if semantic_key:
        return semantic_key
    from_id = str(row.get("from_node_id") or "")
    to_id = str(row.get("to_node_id") or "")
    edge_type = str(row.get("edge_type") or "related_to")
    return f"edge:{from_id}:{to_id}:{edge_type.casefold()}"


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    items: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
    return items


def _entity_key(value: str) -> str:
    normalized = _clean_key_part(value)
    if not normalized:
        return ""
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"person:{normalized}:{digest}"


def _canonical_entity_key(value: str) -> str:
    parts = value.split(":")
    if len(parts) >= 2 and parts[0] == "person" and parts[1]:
        return f"person:{parts[1]}"
    return value


def _clean_key_part(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "_".join(value.strip().casefold().split())


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


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _positive_int(value: object, *, fallback: int) -> int:
    if not isinstance(value, int | float | str | bytes | bytearray):
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback
