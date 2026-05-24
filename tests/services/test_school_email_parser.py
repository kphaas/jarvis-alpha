from datetime import date, time

import pytest

from brain.services.gmail_client import GmailMessage
from brain.services.school_email_parser import (
    extract_school_actions_deterministic,
    extract_school_events,
    extract_school_events_deterministic,
)


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


def test_trusted_sender_allows_teacher_message_without_school_name() -> None:
    candidates = extract_school_events_deterministic(
        _message(
            "Class Picnic",
            "The class picnic is on May 28, 2026 at 11:30am at the playground.",
            sender="teacher@example.com",
        ),
        anchor=date(2026, 5, 24),
        trusted_sender=True,
    )

    assert len(candidates) == 1
    assert candidates[0].event_date == date(2026, 5, 28)


def test_extracts_school_parent_action() -> None:
    candidates = extract_school_actions_deterministic(
        _message(
            "Permission form due",
            "Mount Pisgah permission form is due May 27, 2026 at 9am.",
        ),
        anchor=date(2026, 5, 24),
    )

    assert len(candidates) == 1
    assert candidates[0].title == "Action: Permission form due"
    assert candidates[0].action_date == date(2026, 5, 27)
    assert candidates[0].action_time == time(9, 0)
    assert candidates[0].family_external_id.startswith(
        "alpha:gmail:mount-pisgah:action:"
    )


def test_rolls_missing_year_forward_when_date_is_far_past() -> None:
    candidates = extract_school_events_deterministic(
        _message("Back to School", "Mount Pisgah open house is August 7 at 5pm."),
        anchor=date(2026, 12, 30),
    )

    assert candidates[0].event_date == date(2027, 8, 7)


def test_ignores_stale_explicit_school_dates() -> None:
    candidates = extract_school_events_deterministic(
        _message(
            "Old Lower School event",
            "Mount Pisgah lower school event was February 28, 2024 at 5:30pm.",
        ),
        anchor=date(2026, 5, 24),
    )

    assert candidates == []


def test_ignores_background_check_church_context() -> None:
    candidates = extract_school_events_deterministic(
        _message(
            "Your background check is complete",
            "Your Mount Pisgah Church, Inc. background check is complete.",
            sender="Checkr Background Service <support@checkr.com>",
        ),
        anchor=date(2026, 5, 24),
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_filters_stale_llm_candidates(monkeypatch) -> None:
    monkeypatch.setenv("ALPHA_SCHOOL_EMAIL_USE_LLM", "true")

    class _Response:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {
                "response": (
                    '[{"title":"Daddy/Daughter Dance",'
                    '"event_date":"2024-02-28",'
                    '"event_time":"17:30",'
                    '"location":"Geier Hall",'
                    '"notes":"Old event",'
                    '"confidence":0.98}]'
                )
            }

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, *args, **kwargs) -> _Response:
            return _Response()

    monkeypatch.setattr("brain.services.school_email_parser.httpx.AsyncClient", _Client)

    candidates = await extract_school_events(
        _message(
            "MPCS Lower School Upcoming Patriot Parents Events",
            "Mount Pisgah upcoming event list.",
            sender="Pagona Alford <m@mail1.veracross.com>",
        ),
        anchor=date(2026, 5, 24),
    )

    assert candidates == []
