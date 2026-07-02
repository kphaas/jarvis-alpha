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
from brain.routes import agent_board, tasks

REPO_ROOT = Path(__file__).resolve().parents[1]


def _skill_row(
    name: str,
    approval_tier: str,
    *,
    status: str = "active",
    mutates_state: bool = False,
    metadata: dict[str, object] | None = None,
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
        "metadata": json.dumps(metadata or {}),
    }


def _work_item_row(
    metadata: dict[str, object] | None = None,
    *,
    item_id: UUID | None = None,
    title: str = "Research Hermes patterns",
    description: str = "Prepare operator handoff",
    role: str = "research",
    status: str = "queued",
    priority: int = 8,
    assigned_agent_id: str | None = "internet_scout",
    required_skills: list[str] | None = None,
    approval_tier: str = "T3",
    task_graph_id: UUID | None = None,
    acceptance_criteria: list[str] | None = None,
) -> dict[str, object]:
    now = datetime(2026, 6, 25, 13, 0, tzinfo=UTC)
    return {
        "id": item_id or UUID("11111111-1111-1111-1111-111111111111"),
        "workspace_id": "helm",
        "title": title,
        "description": description,
        "source_surface": "helm_companion",
        "requested_by": "ken",
        "role": role,
        "status": status,
        "priority": priority,
        "assigned_agent_id": assigned_agent_id,
        "assigned_agent_display_name": "Internet Scout",
        "required_skills": required_skills
        if required_skills is not None
        else [
            "internet_scout.deep_research",
            "agent_board.queue_item",
        ],
        "approval_tier": approval_tier,
        "approval_queue_id": None,
        "task_graph_id": task_graph_id,
        "due_at": None,
        "started_at": None,
        "completed_at": None,
        "blocked_reason": None,
        "acceptance_criteria": json.dumps(acceptance_criteria or ["Summarize gaps"]),
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
    skill_map_classes = classify_route("GET", "/v1/agent-board/skill-map")
    create_classes = classify_route("POST", "/v1/agent-board/work-items")
    status_classes = classify_route(
        "PATCH",
        "/v1/agent-board/work-items/11111111-1111-1111-1111-111111111111/status",
    )
    dispatch_classes = classify_route(
        "POST",
        "/v1/agent-board/work-items/11111111-1111-1111-1111-111111111111/task-graph",
    )
    delegate_classes = classify_route(
        "POST",
        "/v1/agent-board/work-items/11111111-1111-1111-1111-111111111111/delegations",
    )
    delegation_dispatch_classes = classify_route(
        "POST",
        "/v1/agent-board/work-items/11111111-1111-1111-1111-111111111111/delegations/dispatch",
    )

    assert determine_risk_tier(read_classes) == "T2"
    assert determine_risk_tier(registry_classes) == "T2"
    assert determine_risk_tier(skill_map_classes) == "T2"
    assert determine_risk_tier(create_classes) == "T2"
    assert determine_risk_tier(status_classes) == "T2"
    assert determine_risk_tier(dispatch_classes) == "T2"
    assert determine_risk_tier(delegate_classes) == "T2"
    assert determine_risk_tier(delegation_dispatch_classes) == "T2"


def test_skill_discovery_entry_maps_skill_policy_to_candidate_agents() -> None:
    skill = next(
        iter(
            agent_board._skills_from_rows(
                [
                    _skill_row(
                        "internet_scout.deep_research",
                        "T3",
                        metadata={
                            "manifest": {
                                "data_classification": "message_body",
                                "side_effect_class": "read",
                                "egress": {"mode": "external"},
                                "cost": {"mode": "metered"},
                                "test_ref": "tests/test_internet_scout_route.py",
                                "runbook_ref": "docs/adr/ADR-0019-beacon-internet-scout.md",
                            },
                            "discovery": {
                                "codex_skill_refs": [
                                    {
                                        "name": "at0-gap-analysis",
                                        "ref": "codex://skills/at0-gap-analysis/SKILL.md",
                                        "description": "Gap analysis operator workflow.",
                                    }
                                ],
                                "claude_skill_refs": [
                                    "claude://skills/anthropic-skills/pdf/SKILL.md"
                                ],
                                "mcp_tool_refs": [
                                    {
                                        "name": "beacon.crawler.scrape",
                                        "ref": "mcp://beacon-crawler/beacon.crawler.scrape",
                                        "metadata": {
                                            "contract_ref": "docs/contracts/beacon_crawler_mcp_adapter.v1.json"
                                        },
                                    }
                                ],
                                "agentfs_refs": [
                                    {
                                        "name": "research_handoff",
                                        "ref": "agentfs://runs/{run_id}/outputs/research-handoff.json",
                                    }
                                ],
                            },
                        },
                    )
                ]
            ).values()
        )
    )
    agents = [
        agent_board.AgentBoardAgentOut(
            agent_id="internet_scout",
            display_name="Internet Scout",
            purpose="Research",
            risk_tier="T4",
            status="active",
            enabled=True,
            allowed_skills=["internet_scout.deep_research"],
            allowed_scopes=["internet_scout.research"],
        ),
        agent_board.AgentBoardAgentOut(
            agent_id="disabled_research",
            display_name="Disabled Research",
            purpose="Research",
            risk_tier="T3",
            status="disabled",
            enabled=False,
            allowed_skills=[],
            allowed_scopes=[skill.scope],
        ),
    ]

    entry = agent_board._skill_discovery_entry(skill, agents)

    assert entry.data_classification == "message_body"
    assert entry.side_effect_class == "read"
    assert entry.egress_mode == "external"
    assert entry.cost_mode == "metered"
    assert entry.runbook_refs[0].ref == "docs/adr/ADR-0019-beacon-internet-scout.md"
    assert entry.codex_skill_refs[0].name == "at0-gap-analysis"
    assert (
        entry.claude_skill_refs[0].ref
        == "claude://skills/anthropic-skills/pdf/SKILL.md"
    )
    assert entry.mcp_tool_refs[0].name == "beacon.crawler.scrape"
    assert (
        entry.mcp_tool_refs[0].metadata["contract_ref"]
        == "docs/contracts/beacon_crawler_mcp_adapter.v1.json"
    )
    assert entry.agentfs_refs[0].ref.endswith("/outputs/research-handoff.json")
    assert entry.allowed_agent_count == 2
    assert entry.enabled_agent_count == 1
    assert entry.candidate_agents[0].agent_id == "internet_scout"
    assert entry.candidate_agents[0].match_type == "allowed_skill"
    assert entry.candidate_agents[1].match_type == "allowed_scope"
    assert entry.assignment_notes == []


def test_skill_discovery_entry_marks_unmapped_skills() -> None:
    skill = next(
        iter(
            agent_board._skills_from_rows(
                [_skill_row("reports.generate", "T2")]
            ).values()
        )
    )

    entry = agent_board._skill_discovery_entry(skill, [])

    assert entry.allowed_agent_count == 0
    assert entry.enabled_agent_count == 0
    assert entry.agentfs_refs[0].ref == "agentfs://runs/{run_id}/artifacts"
    assert entry.agentfs_refs[0].metadata["stores_skill_file_bodies"] is False
    assert entry.assignment_notes == ["no registered agent advertises this skill"]


@pytest.mark.asyncio
async def test_skill_map_route_filters_registry_and_returns_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeConn:
        async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            fetch_calls.append((query, args))
            if "FROM public.alpha_skill_registry" in query:
                assert args == ("internet_scout", "active", "%research%", 25)
                assert "LIMIT $4" in query
                return [_skill_row("internet_scout.deep_research", "T3")]
            assert "FROM public.alpha_agents" in query
            assert args == ()
            return [
                {
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
            ]

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

    request = SimpleNamespace(state=SimpleNamespace(user_id="ken", role="admin"))

    out = await agent_board.get_agent_board_skill_map(
        request,
        query=" research ",
        domain="internet_scout",
        status="active",
        limit=25,
    )

    assert out.count == 1
    assert out.unmapped_skill_count == 0
    assert out.entries[0].skill.name == "internet_scout.deep_research"
    assert out.entries[0].candidate_agents[0].agent_id == "internet_scout"
    assert len(fetch_calls) == 2


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


@pytest.mark.asyncio
async def test_bridge_work_item_creates_task_graph_and_notifies_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_id = UUID("22222222-2222-2222-2222-222222222222")
    step_id = UUID("33333333-3333-3333-3333-333333333333")
    graph_insert_args: tuple[object, ...] | None = None
    step_insert_args: tuple[object, ...] | None = None
    update_args: tuple[object, ...] | None = None
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
            assert "FROM public.alpha_skill_registry" in query
            assert set(args[0]) == {
                "internet_scout.deep_research",
                "agent_board.queue_item",
            }
            return [
                _skill_row("internet_scout.deep_research", "T3"),
                _skill_row("agent_board.queue_item", "T2", mutates_state=True),
            ]

        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            nonlocal graph_insert_args, step_insert_args, update_args
            if "FROM public.alpha_agent_work_items" in query and "FOR UPDATE" in query:
                return _work_item_row()
            if "INSERT INTO public.alpha_task_graphs" in query:
                graph_insert_args = args
                return {"id": graph_id}
            if "INSERT INTO public.alpha_task_steps" in query:
                step_insert_args = args
                return {"id": step_id}
            assert "UPDATE public.alpha_agent_work_items" in query
            update_args = args
            metadata = json.loads(str(args[3]))
            return _work_item_row(
                metadata=metadata,
                status=str(args[2]),
                task_graph_id=graph_id,
            )

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

    request = SimpleNamespace(state=SimpleNamespace(user_id="ken", role="admin"))
    body = agent_board.BridgeWorkItemToTaskGraphRequest()

    out = await agent_board.bridge_work_item_to_task_graph(
        UUID("11111111-1111-1111-1111-111111111111"),
        request,
        body,
    )

    assert out.task_graph_id == str(graph_id)
    assert out.step_id == str(step_id)
    assert out.dispatch_status == "approval_required"
    assert out.approval_required is True
    assert out.work_item.status == "needs_approval"
    assert graph_insert_args is not None
    assert graph_insert_args[0] == "ken"
    assert json.loads(str(graph_insert_args[4]))["work_item_id"] == (
        "11111111-1111-1111-1111-111111111111"
    )
    assert step_insert_args is not None
    assert step_insert_args[3] == "llm"
    assert step_insert_args[5] is True
    assert (
        "Execute this Alpha Agent Board work item"
        in json.loads(str(step_insert_args[4]))["prompt"]
    )
    assert update_args is not None
    assert update_args[2] == "needs_approval"
    assert any("alpha_agent_work_item_events" in call[0] for call in execute_calls)
    assert any("pg_notify('graph_submitted'" in call[0] for call in execute_calls)


@pytest.mark.asyncio
async def test_bridge_work_item_is_idempotent_when_graph_already_linked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_id = UUID("22222222-2222-2222-2222-222222222222")
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
            assert "FROM public.alpha_skill_registry" in query
            return [
                _skill_row("internet_scout.deep_research", "T3"),
                _skill_row("agent_board.queue_item", "T2", mutates_state=True),
            ]

        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            assert "FROM public.alpha_agent_work_items" in query
            return _work_item_row(task_graph_id=graph_id)

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

    request = SimpleNamespace(state=SimpleNamespace(user_id="ken", role="admin"))
    out = await agent_board.bridge_work_item_to_task_graph(
        UUID("11111111-1111-1111-1111-111111111111"),
        request,
        agent_board.BridgeWorkItemToTaskGraphRequest(),
    )

    assert out.dispatch_status == "already_linked"
    assert out.task_graph_id == str(graph_id)
    assert execute_calls == []


@pytest.mark.asyncio
async def test_delegate_work_item_queues_child_items_with_output_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_id = UUID("11111111-1111-1111-1111-111111111111")
    child_ids = [
        UUID("44444444-4444-4444-4444-444444444444"),
        UUID("55555555-5555-5555-5555-555555555555"),
    ]
    inserts: list[tuple[object, ...]] = []
    parent_update: tuple[object, ...] | None = None
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
            assert "FROM public.alpha_skill_registry" in query
            names = set(args[0])
            if names == {"agent_board.queue_item", "internet_scout.deep_research"}:
                return [
                    _skill_row("agent_board.queue_item", "T2", mutates_state=True),
                    _skill_row("internet_scout.deep_research", "T3"),
                ]
            if names == {"agent_board.queue_item"}:
                return [_skill_row("agent_board.queue_item", "T2", mutates_state=True)]
            raise AssertionError(f"unexpected skill lookup: {names}")

        async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
            nonlocal parent_update
            if "FROM public.alpha_agent_work_items" in query and "FOR UPDATE" in query:
                return _work_item_row(
                    {
                        "delegation": {
                            "child_work_item_ids": [
                                "33333333-3333-3333-3333-333333333333"
                            ]
                        }
                    }
                )
            if "INSERT INTO public.alpha_agent_work_items" in query:
                child_id = child_ids[len(inserts)]
                inserts.append(args)
                metadata = json.loads(str(args[12]))
                return _work_item_row(
                    metadata=metadata,
                    item_id=child_id,
                    title=str(args[1]),
                    description=str(args[2]),
                    role=str(args[5]),
                    priority=int(args[6]),
                    assigned_agent_id=args[7] if isinstance(args[7], str) else None,
                    required_skills=list(args[8]),  # type: ignore[arg-type]
                    approval_tier=str(args[9]),
                    acceptance_criteria=json.loads(str(args[11])),
                )
            if "UPDATE public.alpha_agent_work_items" in query:
                parent_update = args
                return _work_item_row(json.loads(str(args[1])))
            raise AssertionError(f"unexpected fetchrow query: {query}")

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

    request = SimpleNamespace(state=SimpleNamespace(user_id="ken", role="admin"))
    body = agent_board.DelegateWorkItemRequest(
        delegations=[
            agent_board.DelegatedWorkItemSpec(
                role="research",
                required_skills=["internet_scout.deep_research"],
                acceptance_criteria=["Return sources"],
                output_contract={
                    "artifact": "research-brief",
                    "format": "markdown",
                },
            ),
            agent_board.DelegatedWorkItemSpec(
                role="review",
                title="Review Hermes handoff",
                required_skills=["agent_board.queue_item"],
            ),
        ]
    )

    out = await agent_board.delegate_work_item(parent_id, request, body)

    assert len(out.children) == 2
    assert out.children[0].metadata["delegation"]["parent_work_item_id"] == str(
        parent_id
    )
    assert out.children[0].metadata["delegation"]["output_contract"] == {
        "artifact": "research-brief",
        "format": "markdown",
    }
    assert (
        out.children[1].metadata["delegation"]["output_contract"]["artifact"]
        == "review-handoff"
    )
    assert (
        out.children[0].metadata["delegation"]["isolated_context"][
            "no_shared_runtime_state"
        ]
        is True
    )
    assert parent_update is not None
    parent_metadata = json.loads(str(parent_update[1]))
    assert parent_metadata["delegation"]["child_work_item_ids"] == [
        "33333333-3333-3333-3333-333333333333",
        str(child_ids[0]),
        str(child_ids[1]),
    ]
    assert len(inserts) == 2
    assert inserts[0][9] == "T3"
    assert inserts[1][9] == "T2"
    assert sum("alpha_agent_work_item_events" in call[0] for call in execute_calls) == 3


@pytest.mark.asyncio
async def test_dispatch_delegated_work_items_bridges_children_and_rolls_up_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_id = UUID("11111111-1111-1111-1111-111111111111")
    child_ids = [
        UUID("44444444-4444-4444-4444-444444444444"),
        UUID("55555555-5555-5555-5555-555555555555"),
    ]
    graph_ids = [
        UUID("66666666-6666-6666-6666-666666666666"),
        UUID("77777777-7777-7777-7777-777777777777"),
    ]
    step_ids = [
        UUID("88888888-8888-8888-8888-888888888888"),
        UUID("99999999-9999-9999-9999-999999999999"),
    ]
    graph_inserts: list[tuple[object, ...]] = []
    step_inserts: list[tuple[object, ...]] = []
    child_updates: list[tuple[object, ...]] = []
    parent_update: tuple[object, ...] | None = None
    execute_calls: list[tuple[str, tuple[object, ...]]] = []

    child_rows = {
        child_ids[0]: _work_item_row(
            {
                "delegation": {
                    "parent_work_item_id": str(parent_id),
                    "role": "research",
                }
            },
            item_id=child_ids[0],
            title="Research child",
            role="research",
            required_skills=["internet_scout.deep_research"],
            approval_tier="T3",
        ),
        child_ids[1]: _work_item_row(
            {
                "delegation": {
                    "parent_work_item_id": str(parent_id),
                    "role": "review",
                }
            },
            item_id=child_ids[1],
            title="Review child",
            role="review",
            required_skills=["agent_board.queue_item"],
            approval_tier="T2",
        ),
    }

    class FakeTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeConn:
        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            assert "FROM public.alpha_skill_registry" in query
            names = set(args[0])
            rows: list[dict[str, object]] = []
            if "internet_scout.deep_research" in names:
                rows.append(_skill_row("internet_scout.deep_research", "T3"))
            if "agent_board.queue_item" in names:
                rows.append(
                    _skill_row("agent_board.queue_item", "T2", mutates_state=True)
                )
            return rows

        async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
            nonlocal parent_update
            if "FROM public.alpha_agent_work_items" in query and "FOR UPDATE" in query:
                item_id = args[0]
                if item_id == parent_id:
                    return _work_item_row(
                        {
                            "delegation": {
                                "child_work_item_ids": [
                                    str(child_ids[0]),
                                    str(child_ids[1]),
                                ]
                            }
                        },
                        item_id=parent_id,
                        title="Parent delegation",
                        role="general",
                        required_skills=["agent_board.queue_item"],
                        approval_tier="T2",
                    )
                return child_rows[item_id]  # type: ignore[index]
            if "INSERT INTO public.alpha_task_graphs" in query:
                graph_id = graph_ids[len(graph_inserts)]
                graph_inserts.append(args)
                return {"id": graph_id}
            if "INSERT INTO public.alpha_task_steps" in query:
                step_id = step_ids[len(step_inserts)]
                step_inserts.append(args)
                return {"id": step_id}
            if (
                "UPDATE public.alpha_agent_work_items" in query
                and "task_graph_id = $2" in query
            ):
                child_updates.append(args)
                child_id = args[0]
                child = child_rows[child_id]  # type: ignore[index]
                return _work_item_row(
                    json.loads(str(args[3])),
                    item_id=child_id,  # type: ignore[arg-type]
                    title=str(child["title"]),
                    role=str(child["role"]),
                    status=str(args[2]),
                    required_skills=list(child["required_skills"]),  # type: ignore[arg-type]
                    approval_tier=str(child["approval_tier"]),
                    task_graph_id=args[1],  # type: ignore[arg-type]
                )
            if "UPDATE public.alpha_agent_work_items" in query:
                parent_update = args
                return _work_item_row(
                    json.loads(str(args[2])),
                    item_id=parent_id,
                    title="Parent delegation",
                    role="general",
                    status=str(args[1]),
                    required_skills=["agent_board.queue_item"],
                    approval_tier="T2",
                )
            raise AssertionError(f"unexpected fetchrow query: {query}")

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

    request = SimpleNamespace(state=SimpleNamespace(user_id="ken", role="admin"))
    out = await agent_board.dispatch_delegated_work_items(
        parent_id,
        request,
        agent_board.DispatchDelegatedWorkItemsRequest(),
    )

    assert out.parent_work_item.status == "in_progress"
    assert [child.task_graph_id for child in out.children] == [
        str(graph_ids[0]),
        str(graph_ids[1]),
    ]
    assert out.children[0].dispatch_status == "approval_required"
    assert out.children[1].dispatch_status == "started"
    assert step_inserts[0][5] is True
    assert step_inserts[1][5] is False
    assert parent_update is not None
    parent_metadata = json.loads(str(parent_update[2]))
    assert parent_metadata["delegation"]["last_dispatch"]["child_work_item_ids"] == [
        str(child_ids[0]),
        str(child_ids[1]),
    ]
    assert (
        parent_metadata["delegation"]["last_dispatch"]["approval_required_count"] == 1
    )
    assert len(graph_inserts) == 2
    assert len(child_updates) == 2
    assert sum("pg_notify('graph_submitted'" in call[0] for call in execute_calls) == 2
    assert sum("alpha_agent_work_item_events" in call[0] for call in execute_calls) == 3


@pytest.mark.asyncio
async def test_delegate_work_item_rejects_closed_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute_calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeConn:
        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            assert "FROM public.alpha_agent_work_items" in query
            return _work_item_row(status="done")

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

    request = SimpleNamespace(state=SimpleNamespace(user_id="ken", role="admin"))
    body = agent_board.DelegateWorkItemRequest(
        delegations=[agent_board.DelegatedWorkItemSpec(role="research")]
    )

    with pytest.raises(agent_board.HTTPException) as exc:
        await agent_board.delegate_work_item(
            UUID("11111111-1111-1111-1111-111111111111"),
            request,
            body,
        )

    assert getattr(exc.value, "status_code") == 409
    assert execute_calls == []


@pytest.mark.asyncio
async def test_approved_task_step_resumes_pending_and_notifies_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_id = "22222222-2222-2222-2222-222222222222"
    execute_calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeConn:
        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            assert "SELECT graph_id::text" in query
            return {
                "graph_id": graph_id,
                "approval_required": True,
                "approval_status": "pending",
                "status": "queued",
            }

        async def execute(self, query: str, *args: object) -> None:
            execute_calls.append((query, args))

    class FakeRlsConnection:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(tasks, "rls_connection", lambda request: FakeRlsConnection())

    request = SimpleNamespace(state=SimpleNamespace(user_id="ken", role="admin"))
    response = await tasks.approve_step(
        "33333333-3333-3333-3333-333333333333",
        request,
    )

    assert response.status_code == 200
    assert "status = 'pending'" in execute_calls[0][0]
    assert execute_calls[0][1][1] == "ken"
    assert any("pg_notify('graph_submitted'" in call[0] for call in execute_calls)


@pytest.mark.asyncio
async def test_approve_step_rejects_non_pending_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute_calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeConn:
        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            assert "SELECT graph_id::text" in query
            return {
                "graph_id": "22222222-2222-2222-2222-222222222222",
                "approval_required": True,
                "approval_status": "approved",
                "status": "queued",
            }

        async def execute(self, query: str, *args: object) -> None:
            execute_calls.append((query, args))

    class FakeRlsConnection:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(tasks, "rls_connection", lambda request: FakeRlsConnection())

    request = SimpleNamespace(state=SimpleNamespace(user_id="ken", role="admin"))
    with pytest.raises(Exception) as exc:
        await tasks.approve_step(
            "33333333-3333-3333-3333-333333333333",
            request,
        )

    assert getattr(exc.value, "status_code") == 409
    assert execute_calls == []


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


def test_agent_board_executor_bridge_skill_migration_is_reversible() -> None:
    migration = (
        REPO_ROOT
        / "brain/db/migrations/20260702_131500_agent_board_executor_bridge.sql"
    )
    rollback = (
        REPO_ROOT
        / "brain/db/rollbacks/20260702_131500_agent_board_executor_bridge_rollback.sql"
    )

    migration_text = migration.read_text(encoding="utf-8")
    rollback_text = rollback.read_text(encoding="utf-8")

    assert "agent_board.dispatch_item" in migration_text
    assert "executor_bridge" in migration_text
    assert "DELETE FROM public.alpha_skill_registry" in rollback_text
    assert "agent_board.dispatch_item" in rollback_text


def test_agent_board_delegation_skill_migration_is_reversible() -> None:
    migration = (
        REPO_ROOT
        / "brain/db/migrations/20260702_213000_agent_board_delegation_skill.sql"
    )
    rollback = (
        REPO_ROOT
        / "brain/db/rollbacks/20260702_213000_agent_board_delegation_skill_rollback.sql"
    )

    migration_text = migration.read_text(encoding="utf-8")
    rollback_text = rollback.read_text(encoding="utf-8")

    assert "agent_board.delegate_item" in migration_text
    assert "delegation_model" in migration_text
    assert "does_not_execute_agents" in migration_text
    assert "DELETE FROM public.alpha_skill_registry" in rollback_text
    assert "agent_board.delegate_item" in rollback_text


def test_chatops_delegation_execution_skill_migration_is_reversible() -> None:
    migration = (
        REPO_ROOT
        / "brain/db/migrations/20260702_233000_chatops_delegation_execution_skills.sql"
    )
    rollback = (
        REPO_ROOT
        / "brain/db/rollbacks/20260702_233000_chatops_delegation_execution_skills_rollback.sql"
    )

    migration_text = migration.read_text(encoding="utf-8")
    rollback_text = rollback.read_text(encoding="utf-8")

    assert "chatops.agent_board_control" in migration_text
    assert "agent_board.dispatch_delegation" in migration_text
    assert "does_not_bypass_alpha_gates" in migration_text
    assert "rolls_up_to_parent" in migration_text
    assert "DELETE FROM public.alpha_skill_registry" in rollback_text
    assert "chatops.agent_board_control" in rollback_text
    assert "agent_board.dispatch_delegation" in rollback_text


def test_skill_discovery_mapping_migration_is_reversible() -> None:
    migration = (
        REPO_ROOT / "brain/db/migrations/20260702_151500_skill_discovery_mapping.sql"
    )
    rollback = (
        REPO_ROOT
        / "brain/db/rollbacks/20260702_151500_skill_discovery_mapping_rollback.sql"
    )

    migration_text = migration.read_text(encoding="utf-8")
    rollback_text = rollback.read_text(encoding="utf-8")

    assert "codex_skill_refs" in migration_text
    assert "claude_skill_refs" in migration_text
    assert "mcp_tool_refs" in migration_text
    assert "agentfs_refs" in migration_text
    assert "docs/contracts/beacon_crawler_mcp_adapter.v1.json" in migration_text
    assert "20260702_151500_skill_discovery_mapping" in rollback_text
    assert "metadata - 'discovery'" in rollback_text
