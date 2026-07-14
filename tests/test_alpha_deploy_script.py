from __future__ import annotations

import subprocess
from pathlib import Path


SCRIPT = Path("scripts/jarvisalpha_deploy.sh")
TRUSTED_CI = Path(".github/workflows/trusted-sandbox-ci.yml")


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
    assert "smoke_memory_graph.py" in text
    assert "JARVIS_SKIP_MEMORY_GRAPH_SMOKE" in text
    assert "JARVIS_ALPHA_SKIP_MEMORY_GRAPH_SMOKE" in text
    assert "smoke_helm_memory_ask_session.py" in text
    assert "MEMORY_ASK_PYTHON" in text
    assert "JARVIS_SKIP_MEMORY_ASK_SMOKE" in text
    assert "JARVIS_ALPHA_SKIP_MEMORY_ASK_SMOKE" in text
    assert "smoke_beacon_production.py" in text
    assert "--skip-agent" in text
    assert "BEACON_SMOKE_SKIP_AGENT=1" in text
    assert 'BEACON_SMOKE_TOKEN_SSH_TARGET="$BRAIN"' in text
    assert "JARVIS_SKIP_BEACON_SMOKE" in text
    assert "JARVIS_ALPHA_SKIP_BEACON_SMOKE" in text
    assert "beacon browser click" in text
    assert "JARVIS_BEACON_BROWSER_CLICK_SMOKE" in text
    assert "JARVIS_ALPHA_BEACON_BROWSER_CLICK_SMOKE" in text
    assert "--run-browser-click" in text
    assert "eval_beacon_answer_engine.py" in text
    assert "JARVIS_SKIP_BEACON_ANSWER_EVAL" in text
    assert "JARVIS_ALPHA_SKIP_BEACON_ANSWER_EVAL" in text
    assert "eval_memory_context.py" in text
    assert "JARVIS_SKIP_MEMORY_CONTEXT_EVAL" in text
    assert "JARVIS_ALPHA_SKIP_MEMORY_CONTEXT_EVAL" in text
    assert "eval_chat_quality.py" in text
    assert "JARVIS_SKIP_CHAT_QUALITY_EVAL" in text
    assert "JARVIS_ALPHA_SKIP_CHAT_QUALITY_EVAL" in text

    endpoint_pull = text.index('remote_pull "Endpoint" "$ENDPOINT"')
    settings_smoke = text.index("run_post_deploy_smokes || DEPLOY_FAILED=1")
    settings_script = text.index('python3 "$REPO_DIR/scripts/smoke_settings.py"')
    memory_script = text.index('python3 "$REPO_DIR/scripts/smoke_memory_core.py"')
    graph_script = text.index('python3 "$REPO_DIR/scripts/smoke_memory_graph.py"')
    memory_ask_script = text.index(
        '"$MEMORY_ASK_PYTHON" "$REPO_DIR/scripts/smoke_helm_memory_ask_session.py"'
    )
    beacon_script = text.index(
        'python3 "$REPO_DIR/scripts/smoke_beacon_production.py" --skip-agent'
    )
    browser_click_script = text.index(
        'python3 "$REPO_DIR/scripts/smoke_beacon_production.py" --skip-agent --run-browser-click'
    )
    answer_eval_script = text.index(
        "uv run --python 3.12 python scripts/eval_beacon_answer_engine.py"
    )
    memory_eval_script = text.index(
        "uv run --python 3.12 python scripts/eval_memory_context.py"
    )
    chat_eval_script = text.index(
        "uv run --python 3.12 python scripts/eval_chat_quality.py"
    )
    done_banner = text.index('done_banner "$HEAD_AFTER" "$total_dur"', settings_smoke)

    assert endpoint_pull < settings_smoke < done_banner
    assert (
        settings_script
        < memory_script
        < graph_script
        < memory_ask_script
        < beacon_script
        < browser_click_script
        < answer_eval_script
        < memory_eval_script
        < chat_eval_script
        < done_banner
    )


def test_trusted_sandbox_ci_runs_chat_quality_gate() -> None:
    text = TRUSTED_CI.read_text(encoding="utf-8")

    assert "Chat quality gates" in text
    assert "uv run --python 3.12 python scripts/eval_chat_quality.py" in text
    assert "ALPHA_CHAT_TRACE_APPROVAL_PUBLIC_KEY_PATH" in text
    assert "Assert chat trace approval trust anchor" in text
    assert "openssl pkey -pubin" in text
