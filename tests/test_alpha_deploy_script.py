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


def test_alpha_deploy_runs_settings_smoke_after_fanout() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "POST-DEPLOY SMOKE" in text
    assert "run_post_deploy_smokes" in text
    assert "smoke_settings.py" in text
    assert 'SETTINGS_SMOKE_TOKEN_SSH_TARGET="$BRAIN"' in text
    assert "JARVIS_SKIP_SETTINGS_SMOKE" in text
    assert "JARVIS_ALPHA_SKIP_SETTINGS_SMOKE" in text

    endpoint_pull = text.index('remote_pull "Endpoint" "$ENDPOINT"')
    settings_smoke = text.index("run_post_deploy_smokes || DEPLOY_FAILED=1")
    done_banner = text.index('done_banner "$HEAD_AFTER" "$total_dur"', settings_smoke)

    assert endpoint_pull < settings_smoke < done_banner
