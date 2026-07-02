from __future__ import annotations

import json
import os
from datetime import UTC, datetime, time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8283")
os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:11434")

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import agent_schedules
from brain.services.agent_schedules import (
    materialize_due_scheduled_work,
    parse_schedule_text,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _skill_row(name: str, approval_tier: str) -> dict[str, object]:
    domain, action = name.split(".", 1)
    return {
        "skill_name": name,
        "domain": domain,
        "action": action,
        "description": f"{name} description",
        "approval_tier": approval_tier,
        "scope": f"{domain}.scope",
        "status": "active",
        "mutates_state": approval_tier != "T1",
        "body_access": False,
        "idempotency_required": approval_tier != "T1",
        "metadata": "{}",
    }


def _schedule_row(
    *,
    metadata: dict[str, object] | None = None,
    next_run_at: datetime | None = None,
    approval_tier: str = "T1",
    status: str = "active",
) -> dict[str, object]:
    now = datetime(2026, 7, 2, 14, 0, tzinfo=UTC)
    return {
        "id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "workspace_id": "helm",
        "title": "Check blocked work",
        "description": "Summarize blocked agents",
        "schedule_text": "every morning",
        "schedule_kind": "daily",
        "day_of_week": None,
        "time_of_day": time(9, 0),
        "timezone": "America/New_York",
        "status": status,
        "source_surface": "helm_companion",
        "role": "monitor",
        "priority": 7,
        "assigned_agent_id": None,
        "required_skills": ["agent_board.read"],
        "approval_tier": approval_tier,
        "next_run_at": next_run_at if next_run_at is not None else now,
        "last_run_at": None,
        "last_work_item_id": None,
        "acceptance_criteria": json.dumps(["Report blocked items"]),
        "metadata": json.dumps(metadata or {}),
        "created_by": "ken",
        "created_at": now,
        "updated_at": now,
    }


def test_parse_schedule_text_supports_common_operator_phrases() -> None:
    now = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)

    morning = parse_schedule_text("check this every morning", now=now)
    nightly = parse_schedule_text("run report nightly", now=now)
    friday_once = parse_schedule_text("follow up Friday", now=now)
    friday_weekly = parse_schedule_text("every Friday at 3pm", now=now)

    assert morning.schedule_kind == "daily"
    assert morning.time_of_day == time(9, 0)
    assert morning.next_run_at.isoformat() == "2026-07-02T13:00:00+00:00"
    assert nightly.schedule_kind == "daily"
    assert nightly.time_of_day == time(22, 0)
    assert nightly.next_run_at.isoformat() == "2026-07-03T02:00:00+00:00"
    assert friday_once.schedule_kind == "once"
    assert friday_once.day_of_week == 4
    assert friday_once.next_run_at.isoformat() == "2026-07-03T13:00:00+00:00"
    assert friday_weekly.schedule_kind == "weekly"
    assert friday_weekly.next_run_at.isoformat() == "2026-07-03T19:00:00+00:00"


def test_parse_schedule_text_rejects_unsupported_cadence() -> None:
    with pytest.raises(ValueError, match="supported cadence"):
        parse_schedule_text(
            "whenever you get a chance",
            now=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        )


def test_parse_schedule_text_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="unsupported timezone"):
        parse_schedule_text(
            "every morning",
            now=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
            timezone_name="Not/A_Zone",
        )


def test_agent_schedule_routes_are_governed_without_execution_tiers() -> None:
    read_classes = classify_route("GET", "/v1/agent-schedules")
    create_classes = classify_route("POST", "/v1/agent-schedules")
    status_classes = classify_route(
        "PATCH",
        "/v1/agent-schedules/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/status",
    )
    materialize_classes = classify_route("POST", "/v1/agent-schedules/materialize-due")

    assert determine_risk_tier(read_classes) == "T2"
    assert determine_risk_tier(create_classes) == "T2"
    assert determine_risk_tier(status_classes) == "T2"
    assert determine_risk_tier(materialize_classes) == "T2"


@pytest.mark.asyncio
async def test_create_scheduled_work_validates_skills_and_stores_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert_args: tuple[object, ...] | None = None

    class FakeConn:
        async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            assert "FROM public.alpha_skill_registry" in query
            assert args == (["internet_scout.deep_research"],)
            return [_skill_row("internet_scout.deep_research", "T3")]

        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            nonlocal insert_args
            assert "INSERT INTO public.alpha_agent_scheduled_work" in query
            insert_args = args
            return _schedule_row(
                metadata=json.loads(str(args[16])),
                next_run_at=args[14],
                approval_tier=str(args[13]),
            )

    class FakeRlsConnection:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(agent_schedules, "check_scopes", lambda *args: None)
    monkeypatch.setattr(
        agent_schedules,
        "rls_connection",
        lambda request: FakeRlsConnection(),
    )

    request = SimpleNamespace(
        state=SimpleNamespace(user_id="ken", workspace_id="helm", role="admin")
    )
    body = agent_schedules.CreateScheduledWorkRequest(
        title="Deep research follow-up",
        description="Check for new material",
        schedule_text="every Friday at 3pm",
        role="research",
        required_skills=["internet_scout.deep_research"],
        acceptance_criteria=["Create board handoff"],
    )

    out = await agent_schedules.create_scheduled_work(request, body)

    assert out.approval_tier == "T3"
    assert out.status == "active"
    assert insert_args is not None
    assert insert_args[3] == "every Friday at 3pm"
    assert insert_args[4] == "weekly"
    assert insert_args[6] == time(15, 0)
    assert insert_args[13] == "T3"


@pytest.mark.asyncio
async def test_materialize_due_scheduled_work_queues_board_item_only() -> None:
    now = datetime(2026, 7, 2, 14, 0, tzinfo=UTC)
    work_item_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
    execute_calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeConn:
        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            assert "FROM public.alpha_agent_scheduled_work" in query
            assert "FOR UPDATE SKIP LOCKED" in query
            assert args == (now, 25)
            return [_schedule_row(next_run_at=now)]

        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            fetchrow_calls.append((query, args))
            assert "INSERT INTO public.alpha_agent_work_items" in query
            assert "alpha_task_graphs" not in query
            assert "pg_notify" not in query
            return {"id": work_item_id}

        async def execute(self, query: str, *args: object) -> None:
            execute_calls.append((query, args))

    items = await materialize_due_scheduled_work(
        FakeConn(),
        now=now,
        actor="agent_scheduler:scheduled",
    )

    assert len(items) == 1
    assert items[0].work_item_id == str(work_item_id)
    assert items[0].schedule_status == "active"
    assert items[0].next_run_at == "2026-07-03T13:00:00+00:00"
    assert len(fetchrow_calls) == 1
    assert json.loads(str(fetchrow_calls[0][1][12]))["scheduled_work"] == {
        "schedule_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "schedule_text": "every morning",
        "materialized_by": "agent_scheduler:scheduled",
        "materialized_at": "2026-07-02T14:00:00+00:00",
    }
    assert any("alpha_agent_work_item_events" in call[0] for call in execute_calls)
    assert any(
        "UPDATE public.alpha_agent_scheduled_work" in call[0] for call in execute_calls
    )
    assert any("alpha_agent_scheduled_work_runs" in call[0] for call in execute_calls)
    assert not any("pg_notify" in call[0] for call in execute_calls)
    assert not any("alpha_task_graphs" in call[0] for call in execute_calls)


def test_agent_schedule_migration_is_reversible_and_rls_guarded() -> None:
    migration = (
        REPO_ROOT / "brain/db/migrations/20260702_140000_agent_scheduled_work.sql"
    )
    rollback = (
        REPO_ROOT
        / "brain/db/rollbacks/20260702_140000_agent_scheduled_work_rollback.sql"
    )

    migration_text = migration.read_text(encoding="utf-8")
    rollback_text = rollback.read_text(encoding="utf-8")

    assert (
        "CREATE TABLE IF NOT EXISTS public.alpha_agent_scheduled_work" in migration_text
    )
    assert "ALTER TABLE public.alpha_agent_scheduled_work FORCE ROW LEVEL SECURITY" in (
        migration_text
    )
    assert "agent_schedule.materialize_due" in migration_text
    assert "does_not_execute_agents" in migration_text
    assert (
        "DROP TABLE IF EXISTS public.alpha_agent_scheduled_work_runs" in rollback_text
    )
    assert "DROP TABLE IF EXISTS public.alpha_agent_scheduled_work" in rollback_text


def test_agent_scheduler_launchagent_is_installed_on_brain() -> None:
    install_script = REPO_ROOT / "scripts/install_launchagents.py"
    plist = REPO_ROOT / "launchagents/com.jarvis.alpha.agent-scheduler.template.plist"
    start_script = REPO_ROOT / "scripts/start_alpha_agent_scheduler.sh"

    assert '"com.jarvis.alpha.agent-scheduler": "brain"' in install_script.read_text(
        encoding="utf-8"
    )
    assert "StartInterval" in plist.read_text(encoding="utf-8")
    assert "-m brain.agents.agent_scheduler" in start_script.read_text(encoding="utf-8")
