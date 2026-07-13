from __future__ import annotations

import plistlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_voice_launchagent_uses_environment_backed_bind_host() -> None:
    plist_path = (
        REPO_ROOT
        / "launchagents"
        / "com.jarvis.alpha.at0-voice.endpoint.template.plist"
    )
    with plist_path.open("rb") as handle:
        command = plistlib.load(handle)["ProgramArguments"][2]

    assert "--host ${JARVIS_AT0_VOICE_BIND_HOST:-127.0.0.1}" in command
    assert "--host 0.0.0.0" not in command


def test_voice_installer_keeps_models_outside_git_checkout() -> None:
    installer = (
        REPO_ROOT / "endpoint" / "voice" / "bin" / "install_at0_voice_runtime.sh"
    ).read_text(encoding="utf-8")

    assert "${HOME}/jarvis/models/faster-whisper-base.en" in installer
    assert "${VOICE_DIR}/models/faster-whisper-base.en" not in installer


def test_voice_health_default_follows_configured_bind_host() -> None:
    pull_script = (REPO_ROOT / "scripts" / "jarvisalpha_pull.sh").read_text(
        encoding="utf-8"
    )

    assert 'AT0_HEALTH_HOST="${JARVIS_AT0_VOICE_BIND_HOST:-127.0.0.1}"' in pull_script
    assert (
        'AT0_HEALTH_URL="${JARVIS_AT0_VOICE_HEALTH_URL:-http://'
        '${AT0_HEALTH_HOST}:4212/health}"'
    ) in pull_script
