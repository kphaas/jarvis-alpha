from brain.dream.read_only_executor import (
    execute_read_only_step,
    is_read_only_tool_step,
)


def test_read_only_tool_step_is_allowlisted():
    step = {
        "name": "inspect_temporal_config",
        "description": "Read the Temporal worker configuration.",
        "agent_type": "tool",
    }

    assert is_read_only_tool_step(step)
    result = execute_read_only_step(step)
    assert result.status == "completed"
    assert result.verification == "read_only_executor_v1"
    assert result.input_hash


def test_write_like_tool_step_is_skipped():
    step = {
        "name": "restart_temporal_worker",
        "description": "Restart the LaunchAgent.",
        "agent_type": "tool",
    }

    assert not is_read_only_tool_step(step)
    result = execute_read_only_step(step)
    assert result.status == "skipped"
    assert result.reason == "not_read_only_allowlisted"


def test_non_tool_step_is_skipped():
    result = execute_read_only_step(
        {
            "name": "summarize_results",
            "description": "Summarize results.",
            "agent_type": "llm",
        }
    )

    assert result.status == "skipped"
    assert result.reason == "unsupported_agent_type:llm"
