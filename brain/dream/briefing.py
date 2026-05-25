"""Dream morning briefing synthesis."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping


DREAM_BRIEFING_SOURCE = "dream_mode"


def _as_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _dt(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _date_value(value: object) -> date:
    dt = _dt(value) or datetime.now(timezone.utc)
    return dt.date()


def _duration_seconds(started_at: object, finished_at: object) -> int:
    start = _dt(started_at)
    finish = _dt(finished_at)
    if not start or not finish:
        return 0
    return max(0, int((finish - start).total_seconds()))


def dream_batch_run_id(session: Mapping[str, Any]) -> str:
    started = _dt(session.get("started_at")) or _dt(session.get("created_at"))
    stamp = (started or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M")
    digest = hashlib.sha256(
        f"{session.get('id')}:{session.get('created_at')}:{session.get('temporal_run_id')}".encode(
            "utf-8"
        )
    ).hexdigest()[:4]
    return f"{stamp}_{digest}"


def _step_outcome(status: str) -> tuple[str, str]:
    value = status.lower()
    if value == "completed":
        return "pass", "PASS"
    if value in {"failed", "blocked"}:
        return "fail", value.upper()
    if value in {"skipped", "pending"}:
        return "skip", value.upper()
    return "skip", value.upper() or "UNKNOWN"


def _result_rows(steps: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for step in steps:
        status = str(step.get("status") or "pending")
        outcome, display = _step_outcome(status)
        duration = _duration_seconds(step.get("started_at"), step.get("finished_at"))
        results.append(
            {
                "feature_id": f"dream_step_{step.get('step_index')}",
                "outcome": outcome,
                "outcome_display": display,
                "cost_usd": _as_float(step.get("cost_usd")),
                "iterations_used": int(step.get("retry_count") or 0),
                "iterations_max": int(step.get("max_retries") or 0),
                "duration_seconds": duration,
                "name": step.get("name"),
                "agent_type": step.get("agent_type"),
                "error_message": step.get("error_message"),
                "verification": step.get("verification"),
            }
        )
    return results


def _markdown(
    session: Mapping[str, Any],
    summary: Mapping[str, Any],
    results: list[Mapping[str, Any]],
) -> str:
    lines = [
        f"# Dream Morning Briefing — Session {session.get('id')}",
        "",
        f"- Status: {session.get('status')}",
        f"- Review verdict: {session.get('review_verdict') or 'n/a'}",
        f"- Cost: ${summary['total_cost_usd']:.4f} of ${summary['per_batch_usd']:.4f}",
        f"- Steps: {summary['pass']} pass, {summary['fail']} fail, {summary['skip']} skip",
    ]
    if session.get("summary"):
        lines.extend(["", "## Summary", str(session["summary"])])

    lines.append("")
    lines.append("## Step Results")
    if not results:
        lines.append("- No persisted Dream steps.")
    for result in results:
        name = result.get("name") or result["feature_id"]
        agent_type = result.get("agent_type") or "unknown"
        line = f"- {result['outcome_display']}: {name} ({agent_type})"
        if result.get("error_message"):
            line += f" — {result['error_message']}"
        lines.append(line)
    return "\n".join(lines)


def build_dream_briefing(
    session: Mapping[str, Any],
    steps: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    step_rows = list(steps)
    results = _result_rows(step_rows)
    pass_count = sum(1 for row in results if row["outcome"] == "pass")
    fail_count = sum(1 for row in results if row["outcome"] == "fail")
    skip_count = sum(1 for row in results if row["outcome"] == "skip")
    budget = _as_float(session.get("cost_budget_usd"))
    cost = _as_float(session.get("cost_actual_usd")) or sum(
        _as_float(row.get("cost_usd")) for row in step_rows
    )
    duration = _duration_seconds(session.get("started_at"), session.get("finished_at"))
    summary = {
        "pass": pass_count,
        "fail": fail_count,
        "skip": skip_count,
        "blocked": sum(1 for step in step_rows if step.get("status") == "blocked"),
        "pending": sum(1 for step in step_rows if step.get("status") == "pending"),
        "total_cost_usd": cost,
        "per_batch_usd": budget,
        "duration_seconds": duration,
        "budget_utilization_pct": round((cost / budget) * 100, 2) if budget else 0,
        "dream_session_id": session.get("id"),
        "dream_status": session.get("status"),
        "review_verdict": session.get("review_verdict"),
    }
    markdown = _markdown(session, summary, results)
    started = _dt(session.get("started_at")) or _dt(session.get("created_at"))
    return {
        "batch_run_id": dream_batch_run_id(session),
        "briefing_date": _date_value(session.get("finished_at") or started),
        "started_at": started or datetime.now(timezone.utc),
        "source": DREAM_BRIEFING_SOURCE,
        "summary": summary,
        "results": results,
        "markdown": markdown,
    }
