from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = Path("scripts/smoke_mvp_user_paths.py")
SPEC = importlib.util.spec_from_file_location("smoke_mvp_user_paths", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
smoke_mvp_user_paths = importlib.util.module_from_spec(SPEC)
sys.modules["smoke_mvp_user_paths"] = smoke_mvp_user_paths
SPEC.loader.exec_module(smoke_mvp_user_paths)


def test_home_weather_summary_passes_for_configured_open_meteo_result():
    payload = {
        "status": "passed",
        "settings_home_coordinates_configured": True,
        "weather_status": "ok",
        "provider": "open-meteo",
        "temperature_f_present": True,
        "observed_at_present": True,
        "condition": "clear",
    }

    assert smoke_mvp_user_paths._home_weather_passed(payload)


def test_internet_scout_summary_counts_citations_and_sources():
    payload = {
        "status": "completed",
        "selected_tool": "search",
        "request_id": "request-1",
        "citations": [{"source_url": "https://open-meteo.com"}],
        "evidence": {"sources": [{"host": "open-meteo.com"}]},
        "raw_web_content_is_untrusted": True,
        "source_quality_status": "supported",
        "confidence": "medium",
        "research_report": {"mode": "deep_research_report"},
    }

    summary = smoke_mvp_user_paths._internet_scout_summary(payload)

    assert summary["citation_count"] == 1
    assert summary["source_count"] == 1
    assert summary["first_source_host"] == "open-meteo.com"
    assert summary["raw_web_content_is_untrusted"] is True


def test_browser_approval_passes_only_for_pending_t4_browser_use():
    summary = {
        "request_id": "request-1",
        "approval_queue_id": "queue-1",
        "approval_status": "pending",
        "selected_tool": "browser_use",
        "requires_approval": True,
        "risk_tier": "T4",
    }

    assert smoke_mvp_user_paths._browser_approval_passed(summary)

    summary["approval_status"] = "approved"
    assert not smoke_mvp_user_paths._browser_approval_passed(summary)


def test_browser_db_verification_requires_no_browser_run_events():
    payload = {"status": "passed", "browser_run_event_count": 0}

    assert smoke_mvp_user_paths._browser_db_verification_passed(payload)
    assert not smoke_mvp_user_paths._browser_db_verification_passed(
        {"status": "passed", "browser_run_event_count": 1}
    )


def test_parse_json_from_stdout_uses_last_json_object():
    payload = smoke_mvp_user_paths._parse_json_from_stdout(
        "log line\n{\"ignored\": true}\n{\"status\": \"passed\"}\n"
    )

    assert payload == {"status": "passed"}


def test_local_base_url_detection():
    assert smoke_mvp_user_paths._is_local_base_url("http://127.0.0.1:8186")
    assert smoke_mvp_user_paths._is_local_base_url("http://localhost:8186")
    assert not smoke_mvp_user_paths._is_local_base_url(
        "https://jarvis-brain.tail40ed36.ts.net:8186"
    )
