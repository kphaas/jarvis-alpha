from uuid import UUID

import pytest

from brain.agents.events import AgentEvent
from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes.chatops import (
    _board_approve_handoff_text,
    _board_queue_text,
    _bounded_limit,
    parse_alpha_command,
)
from brain.routes.registry import _agent_event_from_row, _agent_run_from_row


def test_agent_event_routes_needs_input_to_cross_cutting_channel():
    event = AgentEvent(
        agent_id="approval_triage",
        event_type="approval.queued",
        title="Approval required",
        message="T4 approval queued",
        severity="needs_input",
        channel_key="alpha_events",
    )

    assert event.routed_channel_key == "needs_input"
    assert event.notify_payload()["severity"] == "needs_input"


def test_agent_event_routes_critical_to_alerts():
    event = AgentEvent(
        agent_id="watchdog",
        event_type="watchdog.down",
        title="Brain down",
        message="Brain unreachable",
        severity="critical",
        channel_key="alpha_events",
    )

    assert event.routed_channel_key == "alerts"


def test_mattermost_command_parser_defaults_to_help():
    assert parse_alpha_command("").name == "help"
    parsed = parse_alpha_command("dreams 7")
    assert parsed.name == "dreams"
    assert parsed.args == ("7",)
    board = parse_alpha_command("board queue research check logs")
    assert board.name == "board"
    assert board.args == ("queue", "research", "check", "logs")


def test_mattermost_command_limit_is_bounded():
    assert _bounded_limit((), default=5, maximum=10) == 5
    assert _bounded_limit(("99",), default=5, maximum=10) == 10
    assert _bounded_limit(("nope",), default=5, maximum=10) == 5


def test_mattermost_command_route_is_write_classified():
    classes = classify_route("POST", "/v1/chatops/mattermost/command")

    assert "security_write" in classes
    assert determine_risk_tier(classes) == "T2"


@pytest.mark.asyncio
async def test_mattermost_board_queue_writes_work_item_and_event():
    work_item_id = UUID("11111111-1111-1111-1111-111111111111")
    inserts: list[tuple[object, ...]] = []
    events: list[tuple[object, ...]] = []

    class FakeTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeConn:
        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            assert "INSERT INTO public.alpha_agent_work_items" in query
            inserts.append(args)
            return {
                "id": work_item_id,
                "title": args[0],
                "role": args[2],
                "status": "queued",
            }

        async def execute(self, query: str, *args: object) -> None:
            assert "INSERT INTO public.alpha_agent_work_item_events" in query
            events.append(args)

    text = await _board_queue_text(
        FakeConn(),
        ("research", "Check", "blocked", "agents"),
        "mattermost:ken",
    )

    assert f"Queued `{work_item_id}`" in text
    assert inserts[0][0] == "Check blocked agents"
    assert inserts[0][1] == "mattermost:ken"
    assert inserts[0][2] == "research"
    assert events[0][0] == work_item_id


@pytest.mark.asyncio
async def test_mattermost_board_approve_handoff_requires_handoff_ready():
    work_item_id = UUID("22222222-2222-2222-2222-222222222222")
    writes: list[tuple[str, tuple[object, ...]]] = []

    class FakeTransaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeConn:
        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
            if "SELECT id, title, status" in query:
                return {
                    "id": work_item_id,
                    "title": "Review handoff",
                    "status": "handoff_ready",
                }
            assert "UPDATE public.alpha_agent_work_items" in query
            writes.append((query, args))
            return {"id": work_item_id}

        async def execute(self, query: str, *args: object) -> None:
            writes.append((query, args))

    text = await _board_approve_handoff_text(
        FakeConn(),
        (str(work_item_id),),
        "mattermost:ken",
    )

    assert f"Marked `{work_item_id}` done" in text
    assert any("UPDATE public.alpha_agent_work_items" in call[0] for call in writes)
    assert any("alpha_agent_work_item_events" in call[0] for call in writes)


def test_agent_event_row_conversion():
    row = {
        "id": UUID("11111111-1111-1111-1111-111111111111"),
        "agent_id": "dream_mode",
        "run_id": None,
        "event_type": "dream.completed",
        "severity": "info",
        "title": "Dream completed",
        "message": "Done",
        "correlation_id": "dream:1:cleanup",
        "channel_key": "alpha_events",
        "notification_status": "sent",
        "notification_error": None,
        "payload": '{"session_id": 1}',
        "notification_result": '{"provider": "mattermost"}',
        "created_at": "2026-05-26T00:00:00+00:00",
        "notified_at": None,
    }

    out = _agent_event_from_row(row)

    assert out.id == "11111111-1111-1111-1111-111111111111"
    assert out.payload == {"session_id": 1}
    assert out.notification_result == {"provider": "mattermost"}


def test_agent_run_row_conversion():
    row = {
        "id": UUID("22222222-2222-2222-2222-222222222222"),
        "agent_id": "buddy",
        "status": "succeeded",
        "trigger_type": "scheduled",
        "trace_id": "trace-1",
        "started_at": None,
        "completed_at": None,
        "cost_usd": "0.000000",
        "error_text": None,
        "workspace_backend": "local",
        "workspace_root": "/tmp/22222222-2222-2222-2222-222222222222",
        "policy_labels": "[]",
        "approval_scope": None,
        "retention_class": "standard",
        "artifact_count": 0,
        "metadata": "{}",
        "created_at": "2026-05-26T00:00:00+00:00",
    }

    out = _agent_run_from_row(row)

    assert out.agent_id == "buddy"
    assert out.cost_usd == 0.0
    assert out.workspace_backend == "local"
