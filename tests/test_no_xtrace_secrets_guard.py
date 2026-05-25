from pathlib import Path

from scripts.check_no_xtrace_secrets import find_xtrace_findings


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_finds_shell_xtrace_in_active_scripts(tmp_path):
    _write(
        tmp_path / "scripts" / "start_alpha_brain.sh",
        "#!/usr/bin/env bash\nset -euxo pipefail\nsource ~/jarvis/.secrets\n",
    )
    _write(
        tmp_path / "scripts" / "debug_gateway.sh",
        "#!/usr/bin/env bash\nbash -x scripts/start_alpha_gateway.sh\n",
    )

    findings = find_xtrace_findings(tmp_path, scan_roots=("scripts",))

    assert [(f.path.as_posix(), f.line_number) for f in findings] == [
        ("scripts/debug_gateway.sh", 2),
        ("scripts/start_alpha_brain.sh", 2),
    ]


def test_ignores_handoff_docs_but_accepts_safe_script(tmp_path):
    _write(
        tmp_path / "docs" / "handoffs" / "HANDOFF.md",
        "Past incident: bash -x leaked secrets.\n",
    )
    _write(
        tmp_path / "scripts" / "start_alpha_buddy.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nsource ~/jarvis/.secrets\n",
    )

    assert find_xtrace_findings(tmp_path, scan_roots=("scripts",)) == []


def test_finds_xtrace_in_agent_permission_config(tmp_path):
    _write(
        tmp_path / ".claude" / "settings.local.json",
        '{"permissions":{"allow":["Bash(bash -x scripts/start.sh)"]}}\n',
    )

    findings = find_xtrace_findings(tmp_path, scan_roots=(".claude",))

    assert len(findings) == 1
    assert findings[0].path.as_posix() == ".claude/settings.local.json"
