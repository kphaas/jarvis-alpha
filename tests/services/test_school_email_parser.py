from datetime import date, time

import pytest

from brain.services.gmail_client import GmailMessage
from brain.services.school_email_parser import extract_school_events_deterministic


@pytest.fixture(autouse=True)
def _disable_llm(monkeypatch):
    monkeypatch.setenv("ALPHA_SCHOOL_EMAIL_USE_LLM", "false")


def _message(
    subject: str, body: str, sender: str = "news@mountpisgah.org"
) -> GmailMessage:
    return GmailMessage(
        gmail_message_id="gmail-1",
        thread_id=None,
        history_id=None,
        sender=sender,
        subject=subject,
        received_at=None,
        snippet=body[:80],
        body_text=body,
    )


def test_extracts_school_event_date_time_and_external_id() -> None:
    candidates = extract_school_events_deterministic(
        _message(
            "Lower School Field Trip",
            "Mount Pisgah field trip is on May 28, 2026 at 8:30am at Lower School.",
        ),
        anchor=date(2026, 5, 24),
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.title == "Lower School Field Trip"
    assert candidate.event_date == date(2026, 5, 28)
    assert candidate.event_time == time(8, 30)
    assert candidate.location == "Lower School"
    assert candidate.confidence >= 0.8
    assert candidate.family_external_id.startswith("alpha:gmail:mount-pisgah:")


def test_ignores_non_school_messages() -> None:
    candidates = extract_school_events_deterministic(
        _message(
            "Random sale",
            "This sale is on May 28, 2026 at 8:30am.",
            sender="promo@example.com",
        ),
        anchor=date(2026, 5, 24),
    )

    assert candidates == []


def test_rolls_missing_year_forward_when_date_is_far_past() -> None:
    candidates = extract_school_events_deterministic(
        _message("Back to School", "Mount Pisgah open house is August 7 at 5pm."),
        anchor=date(2026, 12, 30),
    )

    assert candidates[0].event_date == date(2027, 8, 7)
