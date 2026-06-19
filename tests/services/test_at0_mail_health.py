from __future__ import annotations

from datetime import UTC, datetime, timedelta

from brain.services.at0_mail_repository import at0_mail_freshness_status


def _scan(status: str, *, finished_delta_minutes: int):
    now = datetime(2026, 6, 17, 18, 0, tzinfo=UTC)
    return {
        "id": "scan-1",
        "trigger": "scheduled",
        "status": status,
        "started_at": now - timedelta(minutes=finished_delta_minutes + 1),
        "finished_at": now - timedelta(minutes=finished_delta_minutes),
        "mailbox_count": 2,
        "max_results": 25,
        "messages_seen": 0,
        "messages_new": 0,
        "draft_proposals_created": 0,
        "error_type": None,
        "error_message": None,
    }


def test_freshness_is_ok_for_recent_success() -> None:
    now = datetime(2026, 6, 17, 18, 0, tzinfo=UTC)

    result = at0_mail_freshness_status(
        _scan("succeeded", finished_delta_minutes=12),
        now=now,
        stale_after_minutes=180,
    )

    assert result["status"] == "ok"
    assert result["age_minutes"] == 12
    assert result["requires_attention"] is False


def test_freshness_flags_stale_success() -> None:
    now = datetime(2026, 6, 17, 18, 0, tzinfo=UTC)

    result = at0_mail_freshness_status(
        _scan("succeeded", finished_delta_minutes=181),
        now=now,
        stale_after_minutes=180,
    )

    assert result["status"] == "stale"
    assert result["requires_attention"] is True


def test_freshness_flags_failure_even_when_recent() -> None:
    now = datetime(2026, 6, 17, 18, 0, tzinfo=UTC)

    result = at0_mail_freshness_status(
        _scan("failed", finished_delta_minutes=1),
        now=now,
        stale_after_minutes=180,
    )

    assert result["status"] == "failed"
    assert result["requires_attention"] is True


def test_freshness_flags_missing_scan() -> None:
    now = datetime(2026, 6, 17, 18, 0, tzinfo=UTC)

    result = at0_mail_freshness_status(
        None,
        now=now,
        stale_after_minutes=180,
    )

    assert result["status"] == "missing"
    assert result["age_minutes"] is None
    assert result["requires_attention"] is True
