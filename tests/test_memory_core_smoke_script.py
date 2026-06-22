from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = Path("scripts/smoke_memory_core.py")
SPEC = importlib.util.spec_from_file_location("smoke_memory_core", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
smoke_memory_core = importlib.util.module_from_spec(SPEC)
sys.modules["smoke_memory_core"] = smoke_memory_core
SPEC.loader.exec_module(smoke_memory_core)


def test_parse_sse_frame_extracts_memory_payloads_only() -> None:
    payloads = smoke_memory_core._parse_sse_frame(
        [
            "event: message",
            'data: {"delta":"Saved","thread_id":"thread-1"}',
            "data: [DONE]",
        ]
    )

    assert payloads == [{"delta": "Saved", "thread_id": "thread-1"}]


def test_explicit_memory_checks_require_chat_provenance_and_metadata_only_event() -> (
    None
):
    telemetry = {
        "recent_semantic_saves": [
            {
                "id": "memory-1",
                "source_surface": "at0_chat",
                "source_action": "slash_memory_command",
                "review_status": "active",
            }
        ]
    }
    item = {
        "id": "memory-1",
        "category": "preference",
        "provenance": {
            "source_surface": "at0_chat",
            "source_action": "slash_memory_command",
        },
    }

    checks = smoke_memory_core._explicit_memory_checks(
        response_text="Saved to semantic memory as preference.",
        item=item,
        telemetry=telemetry,
    )

    assert all(checks.values())
    telemetry["recent_semantic_saves"][0]["fact"] = "raw fact should fail"
    checks = smoke_memory_core._explicit_memory_checks(
        response_text="Saved to semantic memory as preference.",
        item=item,
        telemetry=telemetry,
    )
    assert checks["telemetry_has_metadata_only_event"] is False


def test_health_review_lane_checks_require_buddy_review_event() -> None:
    result = {
        "saved": True,
        "id": "memory-1",
        "review_required": True,
        "review_status": "pending_review",
        "review_reason": "sensitive_category",
        "buddy_event_id": "buddy-1",
    }
    telemetry = {
        "recent_semantic_saves": [
            {
                "id": "memory-1",
                "source_surface": "memory_core_smoke",
                "source_action": "health_review_lane_probe",
                "review_status": "pending_review",
            }
        ]
    }

    checks = smoke_memory_core._health_review_lane_checks(
        result=result,
        telemetry=telemetry,
    )

    assert all(checks.values())
    result["buddy_event_id"] = None
    checks = smoke_memory_core._health_review_lane_checks(
        result=result,
        telemetry=telemetry,
    )
    assert checks["buddy_event_created"] is False


def test_dream_queue_checks_require_review_gated_t5_proposal_ids() -> None:
    response = {
        "status": "queued",
        "report_status": "review_ready",
        "candidate_count": 1,
        "executable_count": 1,
        "graph_candidate_count": 1,
        "graph_queued_count": 1,
        "graph_existing_count": 0,
        "write_actions_enabled": False,
        "proposals": [
            {
                "proposal_id": "proposal-1",
                "approval_queue_id": "approval-1",
                "proposed_action": "promote_episodic_to_semantic",
                "executable": True,
                "status": "queued",
            }
        ],
        "graph_proposals": [
            {
                "proposal_id": "graph-proposal-1",
                "approval_queue_id": "graph-approval-1",
                "source_kind": "dream",
                "proposed_action": "create_node",
                "object_type": "node",
                "status": "queued",
            }
        ],
    }

    checks = smoke_memory_core._dream_proposal_checks(response=response, dry_run=False)

    assert all(checks.values())
    response["proposals"][0]["approval_queue_id"] = None
    checks = smoke_memory_core._dream_proposal_checks(response=response, dry_run=False)
    assert checks["queued_has_proposal_and_approval_ids"] is False
    response["proposals"][0]["approval_queue_id"] = "approval-1"
    response["graph_proposals"][0]["approval_queue_id"] = None
    checks = smoke_memory_core._dream_proposal_checks(response=response, dry_run=False)
    assert checks["graph_queued_has_proposal_and_approval_ids"] is False


def test_cleanup_sql_scopes_deletes_to_synthetic_marker() -> None:
    sql = smoke_memory_core._cleanup_sql(
        user_id="17eaebb1-d614-5558-bf31-df498d7a61b6",
        smoke_id="abc123",
    )

    assert "memory_core_smoke_abc123" in sql
    assert "summary ILIKE '%abc123%'" in sql
    assert "event.payload->>'source_surface' = 'memory_core_smoke'" in sql
    assert "fact ILIKE '%abc123%'" in sql
    assert "alpha_memory_graph_proposals" in sql
    assert "dream_buddy_graph_extraction" in sql
    assert "DELETE FROM public.alpha_approval_audit" in sql
    assert "DELETE FROM public.alpha_approval_queue" in sql
