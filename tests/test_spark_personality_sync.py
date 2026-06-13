from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_personality_vault.sh"
PULL_SCRIPT = REPO_ROOT / "scripts" / "jarvisalpha_pull.sh"


def test_personality_sync_uses_ssh_remote_without_github_token() -> None:
    source = SYNC_SCRIPT.read_text(encoding="utf-8")

    assert "github-jarvis-personality:kphaas/jarvis-personality.git" in source
    assert "GIT_TERMINAL_PROMPT=0" in source
    assert "GITHUB_TOKEN" not in source
    assert "https://kphaas:${GITHUB_TOKEN}" not in source
    assert "spark/principals/ken/voice.md" in source
    assert "auto/interfaces/spark_context.yml" in source


def test_brain_pull_syncs_personality_before_runtime_gates() -> None:
    source = PULL_SCRIPT.read_text(encoding="utf-8")

    assert 'if [ "$NODE_SHORT" = "brain" ]; then' in source
    assert 'bash "${REPO_DIR}/scripts/sync_personality_vault.sh"' in source
    assert "emit ok personality_sync" in source
    assert "emit fail personality_sync" in source
    assert source.index("personality_sync") < source.index(
        "Running database migrations"
    )
