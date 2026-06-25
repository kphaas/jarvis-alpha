from __future__ import annotations

import json
import os
from datetime import UTC, datetime
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
from brain.routes import agent_board

REPO_ROOT = Path(__file__).resolve().parents[1]


def _skill_row(
    name: str,
    approval_tier: str,
    *,
    status: str = "active",
    mutates_state: bool = False,
) -> dict[str, object]:
    domain, action = name.split(".", 1)
    return {
        "skill_name": name,
        "domain": domain,
        "action": action,
        "description": f"{name} description",
        "approval_tier": approval_tier,
        "scope": f"{domain}.scope",
        "status": status,
        "mutates_state": mutates_state,
        "body_access": False,
        "idempotency_required": mutates_state,
        "metadata": "{}",
    }


def _work_item_row(metadata: dict[str, object] | None = None) -> dict[str, object]:
    now = datetime(2026, 6, 25, 13, 0, tzinfo=UTC)
    return {
        "id": UUID("11111111-1111-1111-1111-111111111111"),
        "workspace_id": "helm",
        "title": "Research Hermes patterns",
        "description": "Prepare operator handoff",
        "source_surface": "helm_companion",
        "requested_by": "ken",
        "role": "research",
        "status": "queued",
        "priority": 8,
        "assigned_agent_id": "internet_scout",
        "assigned_agent_display_name": "Internet Scout",
        "required_skills": [
            "internet_scout.deep_research",
            "agent_board.queue_item",
        ],
        "approval_tier": "T3",
        "approval_queue_id": None,
        "task_graph_id": None,
        "due_at": None,
        "started_at": None,
        "completed_at": None,
        "blocked_reason": None,
        "acceptance_criteria": json.dumps(["Summarize gaps"]),
        "handoff": "{}",
        "metadata": json.dumps(metadata or {}),
        "created_at": now,
        "updated_at": now,
    }


def test_required_skills_normalize_dedupe_and_validate() -> None:
    assert agent_board.normalize_required_skills(
        ["internet_scout.deep_research", "internet_scout.deep_research"]
    ) == ["internet_scout.deep_research"]

    with pytest.raises(ValueError, match="invalid skill name"):
        agent_board.normalize_required_skills(["Codex Skill"])


def test_highest_approval_tier_uses_skill_registry_policy() -> None:
    skills = list(
        agent_board._skills_from_rows(
            [
                _skill_row("agent_board.queue_item", "T2", mutates_state=True),
                _skill_row("internet_scout.deep_research", "T3"),
            ]
        ).values()
    )

    assert agent_board.highest_approval_tier(skills) == "T3"


def test_work_item_row_conversion_returns_board_payload() -> None:
    skills = agent_board._skills_from_rows(
        [
            _skill_row("agent_board.queue_item", "T2", mutates_state=True),
            _skill_row("internet_scout.deep_research", "T3"),
        ]
    )
    out = agent_board._work_item_from_row(
        _work_item_row(
            {
                "assignment_warnings": [
                    "assigned agent is missing required skills: agent_board.queue_item"
                ]
            }
        ),
        skills,
    )

    assert out.approval_tier == "T3"
    assert out.approval_required is False
    assert out.skills[0].name == "internet_scout.deep_research"
    assert out.assignment_warnings == [
        "assigned agent is missing required skills: agent_board.queue_item"
    ]


def test_agent_board_routes_are_governed_without_execution_tiers() -> None:
    read_classes = classify_route("GET", "/v1/agent-board")
    registry_classes = classify_route("GET", "/v1/agent-board/registry")
    create_classes = classify_route("POST", "/v1/agent-board/work-items")
    status_classes = classify_route(
        "PATCH",
        "/v1/agent-board/work-items/11111111-1111-1111-1111-111111111111/status",
    )

    assert determine_risk_tier(read_classes) == "T2"
    assert determine_risk_tier(registry_classes) == "T2"
    assert determine_risk_tier(create_classes) == "T2"
    assert determine_risk_tier(status_classes) == "T2"


@pytest.mark.asyncio
async def test_create_work_item_validates_skills_and_records_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute_calls: list[tuple[str, tuple[object, ...]]] = []
    insert_args: tuple[object, ...] | None = None

    class FakeConn:
        async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            assert "FROM public.alpha_skill_registry" in query
            assert args == (["internet_scout.deep_research", "agent_board.queue_item"],)
            return [
                _skill_row("internet_scout.deep_research", "T3"),
                _skill_row("agent_board.queue_item", "T2", mutates_state=True),
            ]

        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            nonlocal insert_args
            if "FROM public.alpha_agents" in query:
                return {
                    "agent_id": "internet_scout",
                    "display_name": "Internet Scout",
                    "purpose": "Research",
                    "risk_tier": "T4",
                    "status": "active",
                    "enabled": True,
                    "allowed_skills": ["internet_scout.deep_research"],
                    "allowed_scopes": ["internet_scout.research"],
                    "metadata": "{}",
                }
            assert "INSERT INTO public.alpha_agent_work_items" in query
            insert_args = args
            metadata = json.loads(str(args[12]))
            return _work_item_row(metadata)

        async def execute(self, query: str, *args: object) -> None:
            execute_calls.append((query, args))

    class FakeRlsConnection:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(agent_board, "check_scopes", lambda *args: None)
    monkeypatch.setattr(
        agent_board,
        "rls_connection",
        lambda request: FakeRlsConnection(),
    )

    request = SimpleNamespace(
        state=SimpleNamespace(user_id="ken", workspace_id="helm", role="admin")
    )
    body = agent_board.CreateWorkItemRequest(
        title="Research Hermes patterns",
        description="Prepare operator handoff",
        role="research",
        priority=8,
        assigned_agent_id="internet_scout",
        required_skills=[
            "internet_scout.deep_research",
            "agent_board.queue_item",
        ],
        acceptance_criteria=["Summarize gaps"],
    )

    out = await agent_board.create_work_item(request, body)

    assert out.approval_tier == "T3"
    assert out.required_skills == [
        "internet_scout.deep_research",
        "agent_board.queue_item",
    ]
    assert out.assignment_warnings == [
        "assigned agent is missing required skills: agent_board.queue_item"
    ]
    assert insert_args is not None
    assert insert_args[9] == "T3"
    assert len(execute_calls) == 1
    assert "alpha_agent_work_item_events" in execute_calls[0][0]


def test_agent_board_migration_is_reversible_and_rls_guarded() -> None:
    migration = (
        REPO_ROOT / "brain/db/migrations/20260625_130000_agent_board_work_queue.sql"
    )
    rollback = (
        REPO_ROOT
        / "brain/db/rollbacks/20260625_130000_agent_board_work_queue_rollback.sql"
    )

    migration_text = migration.read_text(encoding="utf-8")
    rollback_text = rollback.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.alpha_agent_work_items" in migration_text
    assert "FORCE ROW LEVEL SECURITY" in migration_text
    assert "agent_work_items_operator_write" in migration_text
    assert "agent_board.queue_item" in migration_text
    assert "DROP TABLE IF EXISTS public.alpha_agent_work_items" in rollback_text
