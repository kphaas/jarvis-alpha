from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "smoke_at0_herald_mail.sh"
RESTORE_DRILL_SCRIPT = REPO_ROOT / "scripts" / "smoke_at0_herald_restore_drill.sh"


def test_at0_herald_smoke_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_at0_herald_restore_drill_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(RESTORE_DRILL_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_at0_herald_smoke_script_covers_required_endpoints() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for path in (
        "/v1/at0-mail/scan",
        "/v1/at0-mail/health",
        "/v1/at0-mail/mailboxes",
        "/v1/at0-mail/spark-profile",
        "/v1/at0-mail/dashboard",
        "/v1/at0-mail/messages",
        "/v1/at0-mail/drafts",
        "/v1/at0-mail/drafts/${SEND_DRAFT_ID}/send",
    ):
        assert path in text
    assert "herald.read,herald.write,at0_mail.read,at0_mail.scan,at0_mail.write" in text
    assert "HERALD_SMOKE_SEND_DRAFT_ID" in text


def test_at0_herald_smoke_script_does_not_print_sensitive_fields() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "access_token" in text
    assert "private_key" in text
    assert "PASS at0-herald-mail smoke" in text
    assert "echo ${TOKEN}" not in text
    assert 'echo "$TOKEN"' not in text


def test_at0_herald_restore_drill_covers_mail_audit_and_monitor_tables() -> None:
    text = RESTORE_DRILL_SCRIPT.read_text(encoding="utf-8")

    for table in (
        "public.alpha_at0_mail_scan_runs",
        "public.alpha_at0_mail_messages",
        "public.alpha_at0_mail_draft_proposals",
        "public.alpha_at0_mail_send_events",
        "public.alpha_at0_mail_graph_health",
    ):
        assert table in text
    assert "pg_dump" in text
    assert "pg_restore" in text
    assert "DROP DATABASE IF EXISTS" in text
    assert "alpha_at0_mail_send_events_immutable" in text
    assert "POSTGRES_PASSWORD" in text
    assert "body_preview" not in text
    assert "proposed_body" not in text
    assert "access_token" not in text
