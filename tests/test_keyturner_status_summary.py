from brain.routes.security import build_keyturner_summaries


def test_keyturner_summaries_cover_oauth_dry_run_and_forecast():
    summaries = build_keyturner_summaries(
        [
            {
                "secret_name": "ALPHA_GMAIL_REFRESH_TOKEN",
                "secret_class": "oauth_refresh_token",
                "status": "due_soon",
                "verify_status": "passed",
                "days_until_due": 6,
                "next_due_at": "2026-06-09T00:00:00+00:00",
                "rotation_path": "scripts/reconnect_alpha_gmail.py",
                "requires_approval": False,
                "requires_console_rotation": False,
            },
            {
                "secret_name": "ALPHA_GMAIL_CLIENT_SECRET",
                "secret_class": "oauth_client_secret",
                "status": "healthy",
                "verify_status": "passed",
                "days_until_due": 120,
                "next_due_at": "2026-10-01T00:00:00+00:00",
                "rotation_path": "google_cloud_console_then_scripts/reconnect_alpha_gmail.py",
                "requires_approval": False,
                "requires_console_rotation": True,
            },
            {
                "secret_name": "POSTGRES_PASSWORD",
                "secret_class": "db_password",
                "status": "healthy",
                "verify_status": None,
                "days_until_due": 30,
                "next_due_at": "2026-07-03T00:00:00+00:00",
                "rotation_path": "manual_db_password_runbook",
                "requires_approval": True,
                "requires_console_rotation": False,
            },
            {
                "secret_name": "BROKEN_SECRET",
                "secret_class": "secret",
                "status": "failed",
                "verify_status": "failed",
                "days_until_due": None,
                "next_due_at": None,
                "rotation_path": "scripts/rotate_secret.py",
                "requires_approval": False,
                "requires_console_rotation": False,
            },
        ]
    )

    assert summaries["oauth_health"]["managed"] == 2
    assert summaries["oauth_health"]["attention"] == 1
    assert summaries["rotation_dry_run"]["console_required"] == 1
    assert summaries["rotation_dry_run"]["approval_gated"] == 1
    assert summaries["rotation_dry_run"]["blocked"] == 1
    assert summaries["forecast"]["next_7_days"] == 1
    assert summaries["forecast"]["next_30_days"] == 2
