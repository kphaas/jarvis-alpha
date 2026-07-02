"""Agent Board scheduled-work helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ScheduleKind = Literal["once", "daily", "weekly"]

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_TIME_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b")


@dataclass(frozen=True, slots=True)
class ParsedSchedule:
    schedule_kind: ScheduleKind
    day_of_week: int | None
    time_of_day: time
    timezone: str
    next_run_at: datetime


@dataclass(frozen=True, slots=True)
class MaterializedScheduledWork:
    schedule_id: str
    work_item_id: str
    next_run_at: str | None
    schedule_status: str


def _time_from_text(text: str, default_hour: int) -> time:
    match = _TIME_RE.search(text)
    if match is None:
        return time(default_hour, 0)
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    suffix = match.group(3)
    if minute > 59:
        raise ValueError("schedule minute must be between 0 and 59")
    if suffix:
        if hour < 1 or hour > 12:
            raise ValueError("12-hour schedule time must be between 1 and 12")
        if suffix == "pm" and hour != 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        raise ValueError("24-hour schedule time must be between 0 and 23")
    return time(hour, minute)


def _next_daily_run(local_now: datetime, run_time: time) -> datetime:
    candidate = datetime.combine(local_now.date(), run_time, tzinfo=local_now.tzinfo)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly_run(local_now: datetime, day_of_week: int, run_time: time) -> datetime:
    days_ahead = (day_of_week - local_now.weekday()) % 7
    candidate_date = local_now.date() + timedelta(days=days_ahead)
    candidate = datetime.combine(candidate_date, run_time, tzinfo=local_now.tzinfo)
    if candidate <= local_now:
        candidate += timedelta(days=7)
    return candidate


def parse_schedule_text(
    schedule_text: str,
    *,
    now: datetime,
    timezone_name: str = "America/New_York",
) -> ParsedSchedule:
    text = " ".join(schedule_text.strip().lower().split())
    if not text:
        raise ValueError("schedule_text must be non-empty")

    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unsupported timezone: {timezone_name}") from exc
    local_now = now.astimezone(tz)
    default_hour = 9
    if "nightly" in text or "every night" in text:
        default_hour = 22
    elif "afternoon" in text:
        default_hour = 15
    elif "evening" in text:
        default_hour = 18
    run_time = _time_from_text(text, default_hour)

    weekday = next((value for name, value in _WEEKDAYS.items() if name in text), None)
    if weekday is not None:
        weekly = f"every {list(_WEEKDAYS.keys())[weekday]}" in text or "weekly" in text
        kind: ScheduleKind = "weekly" if weekly else "once"
        next_local = _next_weekly_run(local_now, weekday, run_time)
        return ParsedSchedule(
            schedule_kind=kind,
            day_of_week=weekday,
            time_of_day=run_time,
            timezone=timezone_name,
            next_run_at=next_local.astimezone(UTC),
        )

    if (
        "nightly" in text
        or "daily" in text
        or "every day" in text
        or "every morning" in text
        or "each morning" in text
        or "every afternoon" in text
        or "every evening" in text
        or "every night" in text
    ):
        next_local = _next_daily_run(local_now, run_time)
        return ParsedSchedule(
            schedule_kind="daily",
            day_of_week=None,
            time_of_day=run_time,
            timezone=timezone_name,
            next_run_at=next_local.astimezone(UTC),
        )

    raise ValueError(
        "schedule_text must include a supported cadence like every morning, nightly, or Friday"
    )


def next_run_after(
    *,
    schedule_kind: str,
    day_of_week: int | None,
    time_of_day: time,
    timezone_name: str,
    after: datetime,
) -> datetime | None:
    if schedule_kind == "once":
        return None
    tz = ZoneInfo(timezone_name)
    local_after = after.astimezone(tz)
    if schedule_kind == "daily":
        return _next_daily_run(local_after, time_of_day).astimezone(UTC)
    if schedule_kind == "weekly" and day_of_week is not None:
        return _next_weekly_run(local_after, day_of_week, time_of_day).astimezone(UTC)
    raise ValueError(f"unsupported schedule_kind: {schedule_kind}")


def _jsonb_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return dict(value)


def _jsonb_list(value: Any) -> list[str]:
    if value is None:
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _coerce_time(value: Any) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        parts = value.split(":")
        return time(int(parts[0]), int(parts[1]))
    raise ValueError("invalid time_of_day")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def materialize_due_scheduled_work(
    conn: Any,
    *,
    now: datetime,
    limit: int = 25,
    actor: str = "agent_scheduler",
) -> list[MaterializedScheduledWork]:
    async with conn.transaction():
        return await _materialize_due_scheduled_work_locked(
            conn,
            now=now,
            limit=limit,
            actor=actor,
        )


async def _materialize_due_scheduled_work_locked(
    conn: Any,
    *,
    now: datetime,
    limit: int,
    actor: str,
) -> list[MaterializedScheduledWork]:
    rows = await conn.fetch(
        """
        SELECT id, workspace_id, title, description, source_surface, role,
               priority, assigned_agent_id, required_skills, approval_tier,
               schedule_text, schedule_kind, day_of_week, time_of_day,
               timezone, next_run_at, created_by, acceptance_criteria, metadata
          FROM public.alpha_agent_scheduled_work
         WHERE status = 'active'
           AND next_run_at <= $1
         ORDER BY next_run_at ASC, priority DESC, created_at ASC
         LIMIT $2
         FOR UPDATE SKIP LOCKED
        """,
        now,
        limit,
    )

    materialized: list[MaterializedScheduledWork] = []
    for row in rows:
        metadata = _jsonb_dict(row["metadata"])
        metadata["scheduled_work"] = {
            "schedule_id": str(row["id"]),
            "schedule_text": row["schedule_text"],
            "materialized_by": actor,
            "materialized_at": now.isoformat(),
        }
        work_item = await conn.fetchrow(
            """
            INSERT INTO public.alpha_agent_work_items (
                workspace_id, title, description, source_surface, requested_by,
                role, priority, assigned_agent_id, required_skills,
                approval_tier, due_at, acceptance_criteria, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9::text[],
                $10, $11, $12::jsonb, $13::jsonb
            )
            RETURNING id
            """,
            row["workspace_id"],
            row["title"],
            row["description"],
            row["source_surface"],
            row["created_by"],
            row["role"],
            row["priority"],
            row["assigned_agent_id"],
            list(row["required_skills"] or []),
            row["approval_tier"],
            row["next_run_at"],
            json.dumps(_jsonb_list(row["acceptance_criteria"])),
            json.dumps(metadata),
        )
        if work_item is None:
            continue

        await conn.execute(
            """
            INSERT INTO public.alpha_agent_work_item_events (
                work_item_id, event_type, actor, to_status, message, metadata
            )
            VALUES ($1, 'created', $2, 'queued', $3, $4::jsonb)
            """,
            work_item["id"],
            actor,
            "scheduled work materialized",
            json.dumps({"schedule_id": str(row["id"])}),
        )

        next_run_at = next_run_after(
            schedule_kind=row["schedule_kind"],
            day_of_week=row["day_of_week"],
            time_of_day=_coerce_time(row["time_of_day"]),
            timezone_name=row["timezone"],
            after=now,
        )
        next_status = "completed" if next_run_at is None else "active"
        await conn.execute(
            """
            UPDATE public.alpha_agent_scheduled_work
               SET last_run_at = $2,
                   last_work_item_id = $3,
                   next_run_at = $4,
                   status = $5
             WHERE id = $1
            """,
            row["id"],
            now,
            work_item["id"],
            next_run_at,
            next_status,
        )
        await conn.execute(
            """
            INSERT INTO public.alpha_agent_scheduled_work_runs (
                scheduled_work_id, work_item_id, run_at, status, metadata
            )
            VALUES ($1, $2, $3, 'queued', $4::jsonb)
            """,
            row["id"],
            work_item["id"],
            now,
            json.dumps({"actor": actor, "next_run_at": _iso(next_run_at)}),
        )
        materialized.append(
            MaterializedScheduledWork(
                schedule_id=str(row["id"]),
                work_item_id=str(work_item["id"]),
                next_run_at=_iso(next_run_at),
                schedule_status=next_status,
            )
        )
    return materialized
