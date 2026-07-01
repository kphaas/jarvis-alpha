from uuid import UUID

from brain.agents.events import AgentEvent
from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes.chatops import _bounded_limit, parse_alpha_command
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


def test_mattermost_command_limit_is_bounded():
    assert _bounded_limit((), default=5, maximum=10) == 5
    assert _bounded_limit(("99",), default=5, maximum=10) == 10
    assert _bounded_limit(("nope",), default=5, maximum=10) == 5


def test_mattermost_command_route_is_read_only_classified():
    classes = classify_route("POST", "/v1/chatops/mattermost/command")

    assert "security_read" in classes
    assert determine_risk_tier(classes) == "T2"


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
        "metadata": "{}",
        "created_at": "2026-05-26T00:00:00+00:00",
    }

    out = _agent_run_from_row(row)

    assert out.agent_id == "buddy"
    assert out.cost_usd == 0.0
    assert out.workspace_backend == "local"
