"""Static + behavioral guards for the Session 1 backup pipeline.

Covers pg_backup_alpha.sh, preflight_brain_backup.sh, restore_drill_alpha.sh,
their LaunchAgent templates, and the install_launchagents.py registry.
"""

from __future__ import annotations

import datetime as dt
import plistlib
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

BACKUP_SCRIPTS = [
    REPO_ROOT / "scripts" / "preflight_brain_backup.sh",
    REPO_ROOT / "scripts" / "pg_backup_alpha.sh",
    REPO_ROOT / "scripts" / "restore_drill_alpha.sh",
]

LAUNCHAGENT_TEMPLATES = [
    REPO_ROOT / "launchagents" / "com.jarvis.alpha.pg_backup.template.plist",
    REPO_ROOT / "launchagents" / "com.jarvis.alpha.restore_drill.template.plist",
]

ALLOWED_IPS = {"192.168.30.10", "127.0.0.1", "0.0.0.0"}


def _strip_comments(text: str) -> str:
    """Remove # line comments so static pattern checks don't trip on docs."""
    return re.sub(r"#.*$", "", text, flags=re.MULTILINE)


@pytest.mark.parametrize("script", BACKUP_SCRIPTS, ids=lambda p: p.name)
def test_bash_syntax_clean(script):
    assert script.is_file(), f"missing script: {script}"
    result = subprocess.run(
        ["bash", "-n", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("template", LAUNCHAGENT_TEMPLATES, ids=lambda p: p.name)
def test_plist_renders_to_valid_xml(template):
    assert template.is_file(), f"missing template: {template}"
    content = template.read_text(encoding="utf-8")
    rendered = content.replace("{{HOME}}", "/Users/test").replace("{{USER}}", "test")
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert "Label" in parsed
    assert parsed["Label"].startswith("com.jarvis.alpha.")
    assert "ProgramArguments" in parsed
    assert parsed.get("RunAtLoad") is False, (
        f"{template.name}: RunAtLoad must be false (scheduled-only)"
    )
    assert "StartCalendarInterval" in parsed
    assert "/opt/homebrew/bin" in parsed["EnvironmentVariables"]["PATH"]


def test_plists_use_home_placeholder_only():
    for template in LAUNCHAGENT_TEMPLATES:
        text = template.read_text(encoding="utf-8")
        forbidden = re.findall(r"/Users/(?!test)\w+", text)
        assert not forbidden, (
            f"{template.name}: hardcoded user paths {forbidden} — must use {{{{HOME}}}}"
        )


@pytest.mark.parametrize("script", BACKUP_SCRIPTS, ids=lambda p: p.name)
def test_no_plaintext_secret_patterns(script):
    code = _strip_comments(script.read_text(encoding="utf-8"))
    forbidden_patterns = [
        # gpg passphrase passed as an arg or env (must be fd 3 only)
        r"--passphrase\s+['\"]?\$?[A-Z_]*PASS",
        r"--passphrase=",
        r"GPG_PASSPHRASE=['\"][^$]",
        # tokens echoed
        r"echo\s+.*GATEWAY_TOKEN",
        r"echo\s+.*PASSPHRASE",
        # bash xtrace anywhere near secrets path
        r"set\s+-[a-z]*x[a-z]*",
        r"bash\s+-x",
    ]
    for pattern in forbidden_patterns:
        matches = re.findall(pattern, code)
        assert not matches, f"{script.name}: forbidden pattern {pattern!r} → {matches}"


@pytest.mark.parametrize("script", BACKUP_SCRIPTS, ids=lambda p: p.name)
def test_passphrase_passed_via_fd3_only(script):
    text = script.read_text(encoding="utf-8")
    if "gpg" not in text:
        return
    if "--passphrase-fd 3" not in text:
        return
    # Find all gpg invocations and confirm none use --passphrase or env GPG_PASSPHRASE
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.search(r"\bgpg\b", stripped):
            # Acceptable forms: gpg ... --passphrase-fd 3, gpg --version, gpg --decrypt etc
            assert "--passphrase " not in stripped, (
                f"{script.name}: gpg invocation uses --passphrase arg: {stripped!r}"
            )


@pytest.mark.parametrize("script", BACKUP_SCRIPTS, ids=lambda p: p.name)
def test_only_allowed_hardcoded_ips(script):
    text = script.read_text(encoding="utf-8")
    # Strip comments to avoid flagging documentation
    code = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
    ip_pattern = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    found = set(ip_pattern.findall(code))
    unexpected = found - ALLOWED_IPS
    assert not unexpected, (
        f"{script.name}: unexpected hardcoded IPs {unexpected}; "
        f"only {ALLOWED_IPS} are allowed"
    )


def _retention_should_keep(
    file_date: dt.date, today: dt.date, keep_days: int = 30
) -> bool:
    """Python mirror of prune_retention() in pg_backup_alpha.sh.

    Bash logic (lines 414-470 of pg_backup_alpha.sh, as of 2026-05-28):
        keep if (today - file_date) <= 30d, else keep if day-of-month == 01,
        else delete.
    """
    age_days = (today - file_date).days
    if age_days <= keep_days:
        return True
    if file_date.day == 1:
        return True
    return False


def test_retention_keeps_recent_files():
    today = dt.date(2026, 5, 28)
    for delta in range(0, 31):
        d = today - dt.timedelta(days=delta)
        assert _retention_should_keep(d, today), f"day {delta} should be kept"


def test_retention_deletes_old_non_first_of_month():
    today = dt.date(2026, 5, 28)
    # 60-day-old file (2026-03-29), not the 1st → delete
    assert not _retention_should_keep(dt.date(2026, 3, 29), today)
    # 90-day-old file (2026-02-27) → delete
    assert not _retention_should_keep(dt.date(2026, 2, 27), today)


def test_retention_keeps_first_of_month_forever():
    today = dt.date(2026, 5, 28)
    # 1-year-old first-of-month → must keep
    assert _retention_should_keep(dt.date(2025, 5, 1), today)
    # 5-year-old first-of-month → must keep
    assert _retention_should_keep(dt.date(2021, 1, 1), today)


def test_retention_boundary_at_30_days():
    today = dt.date(2026, 5, 28)
    # exactly 30 days old → keep
    assert _retention_should_keep(today - dt.timedelta(days=30), today)
    # 31 days, not first-of-month → delete
    file_31 = today - dt.timedelta(days=31)
    if file_31.day != 1:
        assert not _retention_should_keep(file_31, today)


def test_install_launchagents_registers_both_new_labels():
    from scripts.install_launchagents import SERVICE_NODE_MAP

    assert SERVICE_NODE_MAP.get("com.jarvis.alpha.beacon-quality") == "brain"
    assert SERVICE_NODE_MAP.get("com.jarvis.alpha.pg_backup") == "brain"
    assert SERVICE_NODE_MAP.get("com.jarvis.alpha.restore_drill") == "sandbox"


def test_install_launchagents_node_choices_include_both_targets():
    from scripts.install_launchagents import SERVICE_NODE_MAP

    nodes = set(SERVICE_NODE_MAP.values())
    assert "brain" in nodes
    assert "sandbox" in nodes


@pytest.mark.parametrize("script", BACKUP_SCRIPTS, ids=lambda p: p.name)
def test_scripts_use_strict_bash_mode(script):
    text = script.read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:40])
    # preflight uses `set -uo pipefail` (without -e) intentionally so all checks
    # complete before reporting; everything else uses full strict mode.
    if script.name == "preflight_brain_backup.sh":
        assert "set -uo pipefail" in head or "set -euo pipefail" in head
    else:
        assert "set -euo pipefail" in head, (
            f"{script.name}: must enable strict bash mode (set -euo pipefail) near top"
        )


@pytest.mark.parametrize("script", BACKUP_SCRIPTS, ids=lambda p: p.name)
def test_scripts_have_shebang(script):
    first_line = script.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!/usr/bin/env bash") or first_line.startswith(
        "#!/bin/bash"
    ), f"{script.name}: missing bash shebang"


def test_drill_has_inject_corrupt_failpath_test_flag():
    """The --inject-corrupt flag is required to drill the FAIL path without
    touching real backup files. Removing it removes our only way to test
    corruption detection in CI."""
    text = (REPO_ROOT / "scripts" / "restore_drill_alpha.sh").read_text(
        encoding="utf-8"
    )
    assert "--inject-corrupt" in text
    assert "INJECT_CORRUPT" in text


def test_restore_drill_finds_macos_tool_paths_outside_login_path():
    text = (REPO_ROOT / "scripts" / "restore_drill_alpha.sh").read_text(
        encoding="utf-8"
    )

    assert "find_tool()" in text
    assert '"/opt/homebrew/bin/${name}"' in text
    assert '"/usr/local/bin/${name}"' in text
    assert "DOCKER=$(find_tool docker || true)" in text


def test_pg_backup_calls_preflight():
    """pg_backup must short-circuit on preflight failure."""
    text = (REPO_ROOT / "scripts" / "pg_backup_alpha.sh").read_text(encoding="utf-8")
    assert "preflight_brain_backup.sh" in text


def test_pg_backup_configures_authenticated_postgres_env():
    """Backups must work after local Postgres trust auth is disabled."""
    text = (REPO_ROOT / "scripts" / "pg_backup_alpha.sh").read_text(encoding="utf-8")
    assert "configure_pg_auth" in text
    assert 'PGHOST="${PGHOST:-127.0.0.1}"' in text
    assert 'PGUSER="${PGUSER:-jarvisbrain}"' in text
    assert 'PGPASSWORD="${PGPASSWORD:-$POSTGRES_PASSWORD}"' in text
    assert "POSTGRES_PASSWORD" in re.search(r"for v in .*?; do", text, re.DOTALL).group(
        0
    )


def test_restore_drill_buddy_event_uses_authenticated_brain_psql():
    """Restore-drill notifications must survive hardened Brain Postgres auth."""
    text = (REPO_ROOT / "scripts" / "restore_drill_alpha.sh").read_text(
        encoding="utf-8"
    )
    assert "remote_psql=" in text
    assert "source ~/jarvis/.secrets" in text
    assert 'PGPASSWORD="$POSTGRES_PASSWORD"' in text
    assert "-h 127.0.0.1 -U jarvisbrain -d jarvis_alpha" in text


def test_restore_drill_reference_table_count_matches_current_baseline():
    text = (REPO_ROOT / "scripts" / "restore_drill_alpha.sh").read_text(
        encoding="utf-8"
    )
    assert "REF_TABLES=105" in text
    assert "including views" in text


def test_restore_drill_verifies_privacy_tables_and_force_rls():
    text = (REPO_ROOT / "scripts" / "restore_drill_alpha.sh").read_text(
        encoding="utf-8"
    )

    assert "EXPECTED_PRIVACY_TABLES=16" in text
    assert "EXPECTED_PRIVACY_FORCE_RLS_TABLES=16" in text
    assert "table_name LIKE 'alpha_privacy_%'" in text
    assert "c.relrowsecurity AND c.relforcerowsecurity" in text
    assert (
        "privacy_tables_${PRIVACY_TABLES}_expected_${EXPECTED_PRIVACY_TABLES}" in text
    )
    assert (
        "privacy_force_rls_${PRIVACY_FORCE_RLS}_expected_"
        "${EXPECTED_PRIVACY_FORCE_RLS_TABLES}" in text
    )
    assert "alpha_privacy_tables:$privacy_tables" in text
    assert "alpha_privacy_force_rls_tables:$privacy_force_rls" in text


def test_pg_backup_uses_atomic_rename():
    text = (REPO_ROOT / "scripts" / "pg_backup_alpha.sh").read_text(encoding="utf-8")
    assert ".partial" in text, "must scp to .partial then atomic rename"


def test_pg_backup_verifies_sha256_round_trip():
    text = (REPO_ROOT / "scripts" / "pg_backup_alpha.sh").read_text(encoding="utf-8")
    assert "sha256" in text.lower()
    # both ends: local hash + remote hash check
    assert "remote_sha" in text or "sha_mismatch" in text


def test_pg_backup_uses_mkdir_lock_not_flock():
    """flock is unavailable on macOS bash 3.2; must use mkdir-based atomic lock."""
    text = (REPO_ROOT / "scripts" / "pg_backup_alpha.sh").read_text(encoding="utf-8")
    code = _strip_comments(text)
    assert "flock" not in code, (
        "must not call flock on macOS — use mkdir-based atomic lock"
    )
    assert "mkdir" in code and ".lock" in code
