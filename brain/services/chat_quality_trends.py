"""Trend summaries for deterministic Alpha chat-quality evals."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

CHAT_QUALITY_TREND_SCHEMA_VERSION = "chat_quality_trend.v1"
CHAT_QUALITY_TREND_SNAPSHOT_SCHEMA_VERSION = "chat_quality_eval_snapshot.v1"


def summarize_chat_quality_trend(
    current: Mapping[str, object],
    history: Sequence[Mapping[str, object]] = (),
    *,
    window_runs: int = 7,
) -> dict[str, object]:
    """Compare the current eval payload with recent compact snapshots."""
    samples = [
        *_compact_samples(history),
        _compact_sample(current),
    ][-max(1, window_runs) :]
    latest = samples[-1]
    oldest = samples[0]
    failed_runs = sum(1 for sample in samples if sample["failed"] > 0)
    passed_runs = len(samples) - failed_runs
    group_deltas = _group_failed_deltas(oldest, latest)
    trend = _trend_label(samples=samples, group_deltas=group_deltas)
    return {
        "schema_version": CHAT_QUALITY_TREND_SCHEMA_VERSION,
        "window_runs": len(samples),
        "passed_runs": passed_runs,
        "failed_runs": failed_runs,
        "pass_rate_percent": round((passed_runs / len(samples)) * 100),
        "latest_status": latest["status"],
        "latest_passed": latest["passed"],
        "latest_failed": latest["failed"],
        "failed_delta": latest["failed"] - oldest["failed"],
        "passed_delta": latest["passed"] - oldest["passed"],
        "case_count_delta": latest["case_count"] - oldest["case_count"],
        "latest_elapsed_ms": latest["elapsed_ms"],
        "latency_delta_ms": _optional_delta(latest["elapsed_ms"], oldest["elapsed_ms"]),
        "latest_accept_rate": latest["accept_rate"],
        "accept_rate_delta": _optional_delta(
            latest["accept_rate"], oldest["accept_rate"]
        ),
        "latest_escalation_rate": latest["escalation_rate"],
        "escalation_rate_delta": _optional_delta(
            latest["escalation_rate"],
            oldest["escalation_rate"],
        ),
        "active_failed_groups": _failed_groups(latest),
        "regressed_groups": [
            group for group, delta in group_deltas.items() if delta > 0
        ],
        "improved_groups": [
            group for group, delta in group_deltas.items() if delta < 0
        ],
        "trend": trend,
        "next_action": _next_action(trend),
    }


def chat_quality_trend_snapshot(
    payload: Mapping[str, object],
    *,
    recorded_at: str | None = None,
) -> dict[str, object]:
    """Return the metadata-only shape safe to append to local JSONL history."""
    snapshot = {
        "schema_version": CHAT_QUALITY_TREND_SNAPSHOT_SCHEMA_VERSION,
        "suite": str(payload.get("suite") or "alpha_chat_quality"),
        "suite_version": int(payload.get("suite_version") or 0),
        "status": str(payload.get("status") or "unknown"),
        "passed": _int_value(payload.get("passed")),
        "failed": _int_value(payload.get("failed")),
        "case_groups": _mapping_value(payload.get("case_groups")),
        "scoreboard": _mapping_value(payload.get("scoreboard")),
        "reporting": _mapping_value(payload.get("reporting")),
    }
    if recorded_at:
        snapshot["recorded_at"] = recorded_at
    return snapshot


def load_chat_quality_trend_history(
    path: Path,
    *,
    max_entries: int = 50,
) -> list[dict[str, object]]:
    """Load recent JSONL snapshots; malformed lines are ignored."""
    if not path.exists():
        return []
    rows: deque[dict[str, object]] = deque(maxlen=max(1, max_entries))
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except OSError:
        return []
    return list(rows)


def append_chat_quality_trend_snapshot(
    path: Path,
    snapshot: Mapping[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(snapshot), sort_keys=True, separators=(",", ":")))
        handle.write("\n")


def _compact_samples(
    payloads: Sequence[Mapping[str, object]],
) -> list[dict[str, Any]]:
    return [_compact_sample(payload) for payload in payloads]


def _compact_sample(payload: Mapping[str, object]) -> dict[str, Any]:
    scoreboard = _mapping_value(payload.get("scoreboard"))
    reporting = _mapping_value(payload.get("reporting"))
    groups = _mapping_value(payload.get("case_groups"))
    passed = _int_value(payload.get("passed"))
    failed = _int_value(payload.get("failed"))
    return {
        "status": str(payload.get("status") or "unknown"),
        "passed": passed,
        "failed": failed,
        "case_count": passed + failed,
        "elapsed_ms": _optional_int(reporting.get("elapsed_ms")),
        "accept_rate": _optional_float(scoreboard.get("accept_rate")),
        "escalation_rate": _optional_float(scoreboard.get("escalation_rate")),
        "groups": {
            str(group): _int_value(_mapping_value(summary).get("failed"))
            for group, summary in groups.items()
        },
    }


def _failed_groups(sample: Mapping[str, Any]) -> list[str]:
    groups = sample.get("groups")
    if not isinstance(groups, dict):
        return []
    return sorted(str(group) for group, failed in groups.items() if _int_value(failed))


def _group_failed_deltas(
    oldest: Mapping[str, Any],
    latest: Mapping[str, Any],
) -> dict[str, int]:
    old_groups = oldest.get("groups") if isinstance(oldest.get("groups"), dict) else {}
    new_groups = latest.get("groups") if isinstance(latest.get("groups"), dict) else {}
    group_names = sorted({*old_groups, *new_groups})
    return {
        str(group): _int_value(new_groups.get(group))
        - _int_value(old_groups.get(group))
        for group in group_names
    }


def _trend_label(
    *,
    samples: Sequence[Mapping[str, Any]],
    group_deltas: Mapping[str, int],
) -> str:
    if len(samples) == 1:
        return "single_sample"
    latest = samples[-1]
    oldest = samples[0]
    if latest["failed"] > oldest["failed"] or any(
        delta > 0 for delta in group_deltas.values()
    ):
        return "regressing"
    if latest["failed"] < oldest["failed"]:
        return "improving"
    if latest["failed"]:
        return "failing"
    return "stable"


def _next_action(trend: str) -> str:
    return {
        "regressing": "inspect_regressed_groups",
        "failing": "inspect_active_failed_groups",
        "improving": "continue_sampling",
        "stable": "continue_sampling",
        "single_sample": "collect_more_runs",
    }.get(trend, "inspect_trend_source")


def _optional_delta(
    latest: int | float | None,
    oldest: int | float | None,
) -> int | float | None:
    if latest is None or oldest is None:
        return None
    delta = latest - oldest
    return round(delta, 3) if isinstance(delta, float) else delta


def _mapping_value(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None
