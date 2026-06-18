from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = Path("scripts/smoke_at0_mvp_user_paths.py")
SPEC = importlib.util.spec_from_file_location("smoke_at0_mvp_user_paths", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
smoke_at0_mvp_user_paths = importlib.util.module_from_spec(SPEC)
sys.modules["smoke_at0_mvp_user_paths"] = smoke_at0_mvp_user_paths
SPEC.loader.exec_module(smoke_at0_mvp_user_paths)


def test_parse_sse_frame_extracts_json_payloads_only() -> None:
    payloads = smoke_at0_mvp_user_paths._parse_sse_frame(
        [
            "event: message",
            'data: {"internet_mode":"web_search","thread_id":"thread-1"}',
            "data: [DONE]",
        ]
    )

    assert payloads == [{"internet_mode": "web_search", "thread_id": "thread-1"}]


def test_chat_metadata_checks_pass_for_frontdoor_beacon_metadata() -> None:
    case = smoke_at0_mvp_user_paths.ChatSmokeCase(
        name="chat_weather_web_search",
        prompt="weather",
        internet_mode="web_search",
        expected_any_hosts=("open-meteo.com",),
    )
    metadata = {
        "thread_id": "thread-1",
        "internet_request_id": "request-1",
        "internet_mode": "web_search",
        "internet_selected_tool": "search",
        "internet_citation_count": 1,
        "internet_accepted_citation_count": 1,
        "internet_synthesis_required_behavior": "answer_with_citations",
        "internet_automatic_memory_write_allowed": False,
        "internet_memory_promotion_review_required": True,
        "raw_web_content_is_untrusted": True,
        "citations": [
            {
                "host": "api.open-meteo.com",
                "source_url": "https://api.open-meteo.com/v1/forecast",
            }
        ],
    }

    checks = smoke_at0_mvp_user_paths._chat_metadata_checks(metadata, case)

    assert all(checks.values())


def test_chat_metadata_checks_require_untrusted_cited_evidence() -> None:
    case = smoke_at0_mvp_user_paths.ChatSmokeCase(
        name="chat_weather_web_search",
        prompt="weather",
        internet_mode="web_search",
        expected_any_hosts=("open-meteo.com",),
    )
    metadata = {
        "internet_request_id": "request-1",
        "internet_mode": "web_search",
        "internet_selected_tool": "search",
        "internet_citation_count": 0,
        "internet_accepted_citation_count": 0,
        "internet_synthesis_required_behavior": "answer_with_citations",
        "internet_automatic_memory_write_allowed": False,
        "internet_memory_promotion_review_required": True,
        "raw_web_content_is_untrusted": False,
        "citations": [],
    }

    checks = smoke_at0_mvp_user_paths._chat_metadata_checks(metadata, case)

    assert checks["citation_present"] is False
    assert checks["raw_web_content_untrusted"] is False
    assert checks["expected_host_present"] is False


def test_find_pending_approval_matches_queue_id() -> None:
    pending = {
        "pending": [
            {"id": "queue-other", "action_class": ["write"]},
            {
                "id": "queue-1",
                "action_class": ["beacon_browser_use", "external_call"],
            },
        ]
    }

    item = smoke_at0_mvp_user_paths._find_pending_approval(pending, "queue-1")

    assert item == {
        "id": "queue-1",
        "action_class": ["beacon_browser_use", "external_call"],
    }


def test_browser_visibility_checks_require_pending_beacon_action_class() -> None:
    summary = {
        "request_id": "request-1",
        "approval_queue_id": "queue-1",
        "approval_status": "pending",
        "selected_tool": "browser_use",
        "requires_approval": True,
        "risk_tier": "T4",
        "visible_in_pending_queue": True,
        "pending_status": "pending",
        "pending_action_class": ["beacon_browser_use", "external_call"],
    }

    checks = smoke_at0_mvp_user_paths._browser_visibility_checks(summary)

    assert all(checks.values())

    summary["pending_action_class"] = ["external_call"]
    checks = smoke_at0_mvp_user_paths._browser_visibility_checks(summary)

    assert checks["beacon_action_class_visible"] is False


def test_local_base_url_detection() -> None:
    assert smoke_at0_mvp_user_paths._is_local_base_url("http://127.0.0.1:8186")
    assert smoke_at0_mvp_user_paths._is_local_base_url("http://localhost:8186")
    assert not smoke_at0_mvp_user_paths._is_local_base_url(
        "https://jarvis-brain.tail40ed36.ts.net:8186"
    )
