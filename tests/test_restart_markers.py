from __future__ import annotations

import subprocess
from pathlib import Path


HELPER = Path(__file__).resolve().parents[1] / "scripts/lib/restart_markers.sh"


def _run(command: str, cwd: Path) -> str:
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True)
    return _run("git rev-parse HEAD", repo)


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Restart Marker Test"], cwd=repo, check=True
    )


def test_restart_marker_changed_files_uses_marker_when_pull_diff_is_empty(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "brain/agents/privacy_scrub").mkdir(parents=True)
    (repo / "brain/agents/privacy_scrub/state.py").write_text("old\n", encoding="utf-8")
    marker_head = _commit(repo, "initial")
    (repo / "brain/agents/privacy_scrub/state.py").write_text("new\n", encoding="utf-8")
    new_head = _commit(repo, "runtime change")

    output = _run(
        f"source {HELPER}; "
        f"restart_marker_changed_files {repo} {marker_head} {new_head} ''",
        repo,
    )

    assert output == "brain/agents/privacy_scrub/state.py"


def test_restart_marker_changed_files_is_conservative_without_marker(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "brain/agents/privacy_scrub").mkdir(parents=True)
    (repo / "brain/agents/privacy_scrub/state.py").write_text(
        "runtime\n", encoding="utf-8"
    )
    (repo / "docs").mkdir()
    (repo / "docs/readme.md").write_text("doc\n", encoding="utf-8")
    new_head = _commit(repo, "initial")

    output = _run(
        f"source {HELPER}; restart_marker_changed_files {repo} '' {new_head} ''",
        repo,
    )

    assert "brain/agents/privacy_scrub/state.py" in output.splitlines()
    assert "docs/readme.md" in output.splitlines()
