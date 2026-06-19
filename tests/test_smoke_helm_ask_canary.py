from __future__ import annotations

from brain.services.internet_scout.ask_canary import AskCanaryCase
from scripts import smoke_helm_ask_canary as smoke


def test_run_suite_uses_fresh_thread_per_case_when_no_seed(monkeypatch) -> None:
    cases = (
        AskCanaryCase(name="case-a", prompt="A"),
        AskCanaryCase(name="case-b", prompt="B"),
    )
    seen_thread_ids: list[str | None] = []

    def fake_run_case(*, base_url, token, case, thread_id, project_id):
        seen_thread_ids.append(thread_id)
        return [
            {
                "delta": f"answer for {case.name}",
                "thread_id": f"thread-{case.name}",
                "internet_mode": case.request_mode,
                "internet_source_quality_status": "supported",
                "internet_accepted_citation_count": 1,
                "internet_synthesis_required_behavior": "answer_with_citations",
                "internet_automatic_memory_write_allowed": False,
                "internet_memory_promotion_review_required": True,
                "raw_web_content_is_untrusted": True,
                "citations": [
                    {
                        "source_url": "https://platform.openai.com/docs/api-reference",
                        "host": "platform.openai.com",
                    }
                ],
            }
        ]

    monkeypatch.setattr(smoke, "_run_case", fake_run_case)

    evaluation, created_thread_ids = smoke._run_suite(
        base_url="https://example.com",
        token="token",
        cases=cases,
        thread_id=None,
        project_id=1644,
    )

    assert evaluation.passed is True
    assert seen_thread_ids == [None, None]
    assert created_thread_ids == ["thread-case-a", "thread-case-b"]


def test_run_suite_reuses_explicit_seed_thread(monkeypatch) -> None:
    cases = (
        AskCanaryCase(name="case-a", prompt="A"),
        AskCanaryCase(name="case-b", prompt="B"),
    )
    seen_thread_ids: list[str | None] = []

    def fake_run_case(*, base_url, token, case, thread_id, project_id):
        seen_thread_ids.append(thread_id)
        return [
            {
                "delta": f"answer for {case.name}",
                "thread_id": thread_id,
                "internet_mode": case.request_mode,
                "internet_source_quality_status": "supported",
                "internet_accepted_citation_count": 1,
                "internet_synthesis_required_behavior": "answer_with_citations",
                "internet_automatic_memory_write_allowed": False,
                "internet_memory_promotion_review_required": True,
                "raw_web_content_is_untrusted": True,
                "citations": [
                    {
                        "source_url": "https://platform.openai.com/docs/api-reference",
                        "host": "platform.openai.com",
                    }
                ],
            }
        ]

    monkeypatch.setattr(smoke, "_run_case", fake_run_case)

    evaluation, created_thread_ids = smoke._run_suite(
        base_url="https://example.com",
        token="token",
        cases=cases,
        thread_id="seed-thread",
        project_id=1644,
    )

    assert evaluation.passed is True
    assert seen_thread_ids == ["seed-thread", "seed-thread"]
    assert created_thread_ids == []


def test_run_suite_archives_case_threads_when_requested(monkeypatch) -> None:
    cases = (
        AskCanaryCase(name="case-a", prompt="A"),
        AskCanaryCase(name="case-b", prompt="B"),
    )
    archived_thread_ids: list[str] = []

    def fake_run_case(*, base_url, token, case, thread_id, project_id):
        return [
            {
                "delta": f"answer for {case.name}",
                "thread_id": f"thread-{case.name}",
                "internet_mode": case.request_mode,
                "internet_source_quality_status": "supported",
                "internet_accepted_citation_count": 1,
                "internet_synthesis_required_behavior": "answer_with_citations",
                "internet_automatic_memory_write_allowed": False,
                "internet_memory_promotion_review_required": True,
                "raw_web_content_is_untrusted": True,
                "citations": [
                    {
                        "source_url": "https://platform.openai.com/docs/api-reference",
                        "host": "platform.openai.com",
                    }
                ],
            }
        ]

    def fake_archive_thread(*, base_url, token, thread_id):
        archived_thread_ids.append(thread_id)

    monkeypatch.setattr(smoke, "_run_case", fake_run_case)
    monkeypatch.setattr(smoke, "_archive_thread", fake_archive_thread)

    evaluation, created_thread_ids = smoke._run_suite(
        base_url="https://example.com",
        token="token",
        cases=cases,
        thread_id=None,
        project_id=1644,
        archive_case_threads=True,
    )

    assert evaluation.passed is True
    assert created_thread_ids == []
    assert archived_thread_ids == ["thread-case-a", "thread-case-b"]
