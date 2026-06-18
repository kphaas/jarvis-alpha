from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "smoke_at0_herald_mail.sh"


def test_at0_herald_smoke_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
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
    ):
        assert path in text
    assert "herald.read,herald.write,at0_mail.read,at0_mail.scan,at0_mail.write" in text


def test_at0_herald_smoke_script_does_not_print_sensitive_fields() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "access_token" in text
    assert "private_key" in text
    assert "PASS at0-herald-mail smoke" in text
    assert "echo ${TOKEN}" not in text
    assert 'echo "$TOKEN"' not in text
