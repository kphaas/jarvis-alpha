from __future__ import annotations

import json

from brain.agents.buddy_agent import (
    memory_maintenance_changed_count,
    memory_maintenance_event_priority,
    should_write_memory_maintenance_event,
)


def test_noop_memory_maintenance_does_not_write_buddy_event() -> None:
    payload = {
        "user_id": "ken",
        "evicted_working": 0,
        "evicted_episodic": 0,
        "capped_episodic": 0,
        "capped_semantic": 0,
        "errors": [],
    }

    assert should_write_memory_maintenance_event(payload) is False
    assert memory_maintenance_changed_count(payload) == 0
    assert memory_maintenance_event_priority(payload) == 1


def test_memory_maintenance_writes_only_changes_or_errors() -> None:
    changed = json.dumps(
        {
            "evicted_working": 2,
            "evicted_episodic": 0,
            "capped_episodic": 1,
            "capped_semantic": 0,
            "errors": [],
        }
    )
    failed = {
        "evicted_working": 0,
        "evicted_episodic": 0,
        "capped_episodic": 0,
        "capped_semantic": 0,
        "errors": [{"step": "cap_semantic", "error": "timeout"}],
    }

    assert should_write_memory_maintenance_event(changed) is True
    assert memory_maintenance_changed_count(changed) == 3
    assert memory_maintenance_event_priority(changed) == 1
    assert should_write_memory_maintenance_event(failed) is True
    assert memory_maintenance_event_priority(failed) == 3
