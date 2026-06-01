from __future__ import annotations

from datetime import datetime, timedelta, timezone

from brain.services.gmail_oauth_health import _days_remaining, _expires_at, _parse_dt


def test_refresh_token_testing_window_uses_issued_at(monkeypatch) -> None:
    issued = datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("ALPHA_GMAIL_TEST_TOKEN_DAYS", "7")

    expires_at = _expires_at(issued, "testing")

    assert expires_at == issued + timedelta(days=7)
    assert _days_remaining(expires_at, issued + timedelta(hours=1)) == 6


def test_refresh_token_production_mode_has_no_countdown() -> None:
    issued = datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc)

    assert _expires_at(issued, "production") is None


def test_parse_dt_normalizes_zulu_time() -> None:
    assert _parse_dt("2026-06-01T18:00:00Z") == datetime(
        2026, 6, 1, 18, 0, tzinfo=timezone.utc
    )
