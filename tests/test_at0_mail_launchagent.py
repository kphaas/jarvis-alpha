from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PLIST = REPO_ROOT / "launchagents" / "com.jarvis.alpha.at0-mail.template.plist"
START_SCRIPT = REPO_ROOT / "scripts" / "start_alpha_at0_mail.sh"


def test_at0_mail_launchagent_template_renders() -> None:
    rendered = PLIST.read_text(encoding="utf-8").replace("{{HOME}}", "/Users/test")
    parsed = plistlib.loads(rendered.encode("utf-8"))

    assert parsed["Label"] == "com.jarvis.alpha.at0-mail"
    assert parsed["RunAtLoad"] is False
    assert parsed["StartInterval"] == 3600
    assert parsed["ProgramArguments"] == [
        "/bin/bash",
        "/Users/test/jarvis-alpha/scripts/start_alpha_at0_mail.sh",
    ]


def test_at0_mail_start_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(START_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "-m brain.agents.at0_mail_watcher" in START_SCRIPT.read_text(
        encoding="utf-8"
    )


def test_at0_mail_launchagent_registered_for_brain() -> None:
    from scripts.install_launchagents import SERVICE_NODE_MAP

    assert SERVICE_NODE_MAP.get("com.jarvis.alpha.at0-mail") == "brain"
