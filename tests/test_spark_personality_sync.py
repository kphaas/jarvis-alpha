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


def test_pull_deploy_refuses_remote_feature_branch_by_default() -> None:
    source = PULL_SCRIPT.read_text(encoding="utf-8")

    assert "CURRENT_BRANCH=$(git branch --show-current" in source
    assert "JARVIS_ALPHA_ALLOW_BRANCH_DEPLOY:-0" in source
    assert "REMOTE BRANCH GUARD FAILED" in source
    assert source.index("CURRENT_BRANCH=$(git branch --show-current") < source.index(
        "git pull origin main --rebase"
    )


def test_pull_deploy_refuses_head_that_is_not_origin_main() -> None:
    source = PULL_SCRIPT.read_text(encoding="utf-8")

    assert 'ORIGIN_MAIN_FULL=$(git -C "$REPO_DIR" rev-parse' in source
    assert "refs/remotes/origin/main" in source
    assert "REMOTE HEAD GUARD FAILED" in source
    assert "remote head is not origin/main after pull" in source


def test_pull_deploy_refuses_dirty_or_unmerged_remote_worktree_before_pull() -> None:
    source = PULL_SCRIPT.read_text(encoding="utf-8")

    assert "git ls-files -u | grep -q ." in source
    assert "remote worktree has unmerged paths before pull" in source
    assert 'if [ -n "$(git status --porcelain)" ]; then' in source
    assert "remote worktree is dirty before pull" in source
    assert "REMOTE WORKTREE GUARD FAILED" in source
    assert source.index("git ls-files -u | grep -q .") < source.index(
        "git pull origin main --rebase"
    )
    assert source.index('if [ -n "$(git status --porcelain)" ]; then') < source.index(
        "git pull origin main --rebase"
    )
