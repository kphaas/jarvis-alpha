from __future__ import annotations

import subprocess
from pathlib import Path


SCRIPT = Path("scripts/jarvisalpha_deploy.sh")


def test_alpha_deploy_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_alpha_deploy_runs_cheap_smokes_after_fanout() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "POST-DEPLOY SMOKE" in text
    assert "run_post_deploy_smokes" in text
    assert "smoke_settings.py" in text
    assert 'SETTINGS_SMOKE_TOKEN_SSH_TARGET="$BRAIN"' in text
    assert "JARVIS_SKIP_SETTINGS_SMOKE" in text
    assert "JARVIS_ALPHA_SKIP_SETTINGS_SMOKE" in text
    assert "smoke_memory_core.py" in text
    assert "JARVIS_SKIP_MEMORY_CORE_SMOKE" in text
    assert "JARVIS_ALPHA_SKIP_MEMORY_CORE_SMOKE" in text
    assert "smoke_beacon_production.py" in text
    assert "--skip-agent" in text
    assert "BEACON_SMOKE_SKIP_AGENT=1" in text
    assert 'BEACON_SMOKE_TOKEN_SSH_TARGET="$BRAIN"' in text
    assert "JARVIS_SKIP_BEACON_SMOKE" in text
    assert "JARVIS_ALPHA_SKIP_BEACON_SMOKE" in text

    endpoint_pull = text.index('remote_pull "Endpoint" "$ENDPOINT"')
    settings_smoke = text.index("run_post_deploy_smokes || DEPLOY_FAILED=1")
    settings_script = text.index('python3 "$REPO_DIR/scripts/smoke_settings.py"')
    memory_script = text.index('python3 "$REPO_DIR/scripts/smoke_memory_core.py"')
    beacon_script = text.index(
        'python3 "$REPO_DIR/scripts/smoke_beacon_production.py" --skip-agent'
    )
    done_banner = text.index('done_banner "$HEAD_AFTER" "$total_dur"', settings_smoke)

    assert endpoint_pull < settings_smoke < done_banner
    assert settings_script < memory_script < beacon_script < done_banner
