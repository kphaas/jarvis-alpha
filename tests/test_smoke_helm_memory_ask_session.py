from __future__ import annotations

from scripts import smoke_helm_memory_ask_session as smoke


def test_memory_ask_payload_eval_passes_clean_memory_answer() -> None:
    result = smoke.evaluate_memory_ask_payloads(
        [
            {
                "delta": (
                    "- Memory: Ken has a current career profile as an "
                    "enterprise AI architect."
                ),
                "model": "llama3.1",
                "thread_id": "thread-1",
            },
            {"delta": "", "model": "llama3.1", "thread_id": "thread-1", "done": True},
        ]
    )

    assert result["status"] == "passed"
    assert result["failures"] == []
    assert result["checks"]["web_suggestion_metadata_absent"] is True


def test_memory_ask_payload_eval_fails_web_fallback() -> None:
    result = smoke.evaluate_memory_ask_payloads(
        [
            {
                "web_suggestion_mode": "web_search",
                "web_suggestion_reason": "current_information_likely",
                "thread_id": "thread-1",
            },
            {
                "delta": "I need to verify that first. Use Web search.",
                "model": "beacon/insufficient-evidence",
                "thread_id": "thread-1",
            },
            {
                "delta": "",
                "model": "beacon/insufficient-evidence",
                "thread_id": "thread-1",
                "done": True,
            },
        ]
    )

    assert result["status"] == "failed"
    assert "beacon_insufficient_model_absent" in result["failures"]
    assert "web_suggestion_metadata_absent" in result["failures"]
    assert "web_fallback_copy_absent" in result["failures"]


def test_memory_ask_payload_eval_fails_internet_metadata() -> None:
    result = smoke.evaluate_memory_ask_payloads(
        [
            {
                "internet_mode": "deep_research",
                "internet_source_quality_status": "supported",
                "thread_id": "thread-1",
            },
            {
                "delta": "- Memory: Ken has approved career profile facts.",
                "model": "llama3.1",
                "thread_id": "thread-1",
            },
        ]
    )

    assert result["status"] == "failed"
    assert "internet_metadata_absent" in result["failures"]
