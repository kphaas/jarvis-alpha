from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PLIST = (
    REPO_ROOT
    / "launchagents"
    / "com.jarvis.alpha.herald-linkedin-health.template.plist"
)
WEEKLY_PLIST = (
    REPO_ROOT
    / "launchagents"
    / "com.jarvis.alpha.herald-linkedin-weekly-draft.template.plist"
)
ENGAGEMENT_PLIST = (
    REPO_ROOT
    / "launchagents"
    / "com.jarvis.alpha.herald-linkedin-engagement-scheduler.template.plist"
)
START_SCRIPT = REPO_ROOT / "scripts" / "start_alpha_herald_linkedin_health.sh"
WEEKLY_START_SCRIPT = (
    REPO_ROOT / "scripts" / "start_alpha_herald_linkedin_weekly_draft.sh"
)
ENGAGEMENT_START_SCRIPT = (
    REPO_ROOT / "scripts" / "start_alpha_herald_linkedin_engagement_scheduler.sh"
)
PULL_SCRIPT = REPO_ROOT / "scripts" / "jarvisalpha_pull.sh"
WEEKLY_AGENT = REPO_ROOT / "brain" / "agents" / "herald_linkedin_weekly_draft.py"
ENGAGEMENT_AGENT = (
    REPO_ROOT / "brain" / "agents" / "herald_linkedin_engagement_scheduler.py"
)


def test_herald_linkedin_health_launchagent_template_renders() -> None:
    rendered = PLIST.read_text(encoding="utf-8").replace("{{HOME}}", "/Users/test")
    parsed = plistlib.loads(rendered.encode("utf-8"))

    assert parsed["Label"] == "com.jarvis.alpha.herald-linkedin-health"
    assert parsed["RunAtLoad"] is True
    assert parsed["StartInterval"] == 21600
    assert parsed["ProgramArguments"] == [
        "/bin/bash",
        "/Users/test/jarvis-alpha/scripts/start_alpha_herald_linkedin_health.sh",
    ]


def test_herald_linkedin_health_start_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(START_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "-m brain.agents.herald_linkedin_health_watcher" in START_SCRIPT.read_text(
        encoding="utf-8"
    )


def test_herald_linkedin_weekly_launchagent_template_renders() -> None:
    rendered = WEEKLY_PLIST.read_text(encoding="utf-8").replace(
        "{{HOME}}", "/Users/test"
    )
    parsed = plistlib.loads(rendered.encode("utf-8"))

    assert parsed["Label"] == "com.jarvis.alpha.herald-linkedin-weekly-draft"
    assert parsed["RunAtLoad"] is True
    assert parsed["StartInterval"] == 86400
    assert parsed["ProgramArguments"] == [
        "/bin/bash",
        "/Users/test/jarvis-alpha/scripts/start_alpha_herald_linkedin_weekly_draft.sh",
    ]


def test_herald_linkedin_weekly_start_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(WEEKLY_START_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (
        "-m brain.agents.herald_linkedin_weekly_draft"
        in WEEKLY_START_SCRIPT.read_text(encoding="utf-8")
    )


def test_herald_linkedin_engagement_launchagent_template_renders() -> None:
    rendered = ENGAGEMENT_PLIST.read_text(encoding="utf-8").replace(
        "{{HOME}}", "/Users/test"
    )
    parsed = plistlib.loads(rendered.encode("utf-8"))

    assert parsed["Label"] == "com.jarvis.alpha.herald-linkedin-engagement-scheduler"
    assert parsed["RunAtLoad"] is True
    assert parsed["StartInterval"] == 86400
    assert parsed["ProgramArguments"] == [
        "/bin/bash",
        "/Users/test/jarvis-alpha/scripts/start_alpha_herald_linkedin_engagement_scheduler.sh",
    ]


def test_herald_linkedin_engagement_start_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(ENGAGEMENT_START_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (
        "-m brain.agents.herald_linkedin_engagement_scheduler"
        in ENGAGEMENT_START_SCRIPT.read_text(encoding="utf-8")
    )


def test_herald_linkedin_health_launchagent_registered_for_brain() -> None:
    from scripts.install_launchagents import SERVICE_NODE_MAP

    assert (
        SERVICE_NODE_MAP.get("com.jarvis.alpha.herald-linkedin-engagement-scheduler")
        == "brain"
    )
    assert SERVICE_NODE_MAP.get("com.jarvis.alpha.herald-linkedin-health") == "brain"
    assert (
        SERVICE_NODE_MAP.get("com.jarvis.alpha.herald-linkedin-weekly-draft") == "brain"
    )


def test_pull_script_refreshes_herald_linkedin_launchagents() -> None:
    source = PULL_SCRIPT.read_text(encoding="utf-8")

    assert "needs_reload_herald_linkedin" in source
    assert "com.jarvis.alpha.herald-linkedin-engagement-scheduler.plist" in source
    assert "com.jarvis.alpha.herald-linkedin-health.plist" in source
    assert "com.jarvis.alpha.herald-linkedin-weekly-draft.plist" in source


def test_weekly_agent_does_not_log_reserved_created_field() -> None:
    source = WEEKLY_AGENT.read_text(encoding="utf-8")

    assert '"draft_created": outcome.created' in source
    assert '"created": outcome.created' not in source


def test_engagement_agent_logs_safe_fields() -> None:
    source = ENGAGEMENT_AGENT.read_text(encoding="utf-8")

    assert '"draft_count": outcome.created_count' in source
    assert '"created": outcome.created_count' not in source
