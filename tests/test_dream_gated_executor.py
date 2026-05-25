from brain.dream.gated_executor import (
    build_write_approval_plan,
    decode_gate_verification,
    encode_gate_verification,
)


def test_read_only_step_does_not_need_write_gate():
    step = {
        "id": 1,
        "session_id": 10,
        "step_index": 1,
        "name": "inspect_temporal_worker",
        "description": "Read the worker heartbeat.",
        "agent_type": "tool",
    }

    assert build_write_approval_plan(step) is None


def test_write_step_is_t4_autonomous_gate():
    step = {
        "id": 2,
        "session_id": 10,
        "step_index": 2,
        "name": "update_briefing_row",
        "description": "Write the generated morning briefing row.",
        "agent_type": "tool",
    }

    plan = build_write_approval_plan(step)

    assert plan is not None
    assert plan.risk_tier == "T4"
    assert "dream_autonomous" in plan.action_classes
    assert plan.requires_post_action_verification
    assert plan.parameters_hash


def test_high_risk_step_is_t5_and_round_trips_verification():
    step = {
        "id": 3,
        "session_id": 10,
        "step_index": 3,
        "name": "restart_launchagent",
        "description": "Restart the LaunchAgent and rotate a secret.",
        "agent_type": "code",
    }

    plan = build_write_approval_plan(step)
    verification = encode_gate_verification("queue-id", plan)
    decoded = decode_gate_verification(verification)

    assert plan.risk_tier == "T5"
    assert "admin" in plan.action_classes
    assert "deploy" in plan.action_classes
    assert plan.requires_compensation_metadata
    assert decoded["queue_id"] == "queue-id"
    assert decoded["risk_tier"] == "T5"
