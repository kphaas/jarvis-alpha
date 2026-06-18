from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT_PATH = Path("scripts/smoke_privacy_agent.py")
SPEC = importlib.util.spec_from_file_location("smoke_privacy_agent", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
smoke_privacy_agent = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke_privacy_agent
SPEC.loader.exec_module(smoke_privacy_agent)


def test_privacy_smoke_token_uses_explicit_token(monkeypatch) -> None:
    monkeypatch.setenv("PRIVACY_SMOKE_TOKEN", "privacy-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")

    token = smoke_privacy_agent._smoke_token(
        profile="ken",
        base_url=smoke_privacy_agent.DEFAULT_BASE_URL,
        token_ssh_target=None,
    )

    assert token == "privacy-token"


def test_privacy_smoke_token_uses_target_side_user_token(monkeypatch) -> None:
    monkeypatch.delenv("PRIVACY_SMOKE_TOKEN", raising=False)
    calls: list[list[str]] = []

    def fake_check_output(cmd, *, text, stderr):
        calls.append(cmd)
        return "target-user-token\n"

    monkeypatch.setattr(
        smoke_privacy_agent.subprocess,
        "check_output",
        fake_check_output,
    )

    token = smoke_privacy_agent._smoke_token(
        profile="ken",
        base_url=smoke_privacy_agent.DEFAULT_BASE_URL,
        token_ssh_target="jarvisbrain@example.test",
    )

    assert token == "target-user-token"
    assert calls[0][0] == "ssh"
    assert calls[0][-2] == "jarvisbrain@example.test"
    assert "scripts/gen_test_token.py ken" in calls[0][-1]


def test_privacy_smoke_without_token_source_fails_explicitly(monkeypatch) -> None:
    monkeypatch.delenv("PRIVACY_SMOKE_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="PRIVACY_SMOKE_TOKEN"):
        smoke_privacy_agent._smoke_token(
            profile="ken",
            base_url=smoke_privacy_agent.DEFAULT_BASE_URL,
            token_ssh_target=None,
        )


def test_privacy_smoke_approval_pin_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("PRIVACY_SMOKE_APPROVAL_PIN", "explicit-pin")

    assert smoke_privacy_agent._approval_pin(require_explicit=True) == "explicit-pin"


def test_privacy_smoke_approval_pin_reads_alpha_pin_from_secret_file(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("PRIVACY_SMOKE_APPROVAL_PIN", raising=False)
    home = tmp_path / "home"
    secrets_dir = home / "jarvis"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / ".secrets").write_text(
        "ALPHA_PIN=secret-pin\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(smoke_privacy_agent.Path, "home", lambda: home)

    assert smoke_privacy_agent._approval_pin() == "secret-pin"


def test_privacy_smoke_remote_approval_pin_requires_explicit_env(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("PRIVACY_SMOKE_APPROVAL_PIN", raising=False)
    home = tmp_path / "home"
    secrets_dir = home / "jarvis"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / ".secrets").write_text(
        "ALPHA_PIN=stale-legacy-pin\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(smoke_privacy_agent.Path, "home", lambda: home)

    with pytest.raises(smoke_privacy_agent.SmokeSkip, match="ALPHA_PIN fallback"):
        smoke_privacy_agent._approval_pin(require_explicit=True)


def test_privacy_smoke_approval_pin_accepts_exported_secret_line(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("PRIVACY_SMOKE_APPROVAL_PIN", raising=False)
    home = tmp_path / "home"
    secrets_dir = home / "jarvis"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / ".secrets").write_text(
        "export PRIVACY_SMOKE_APPROVAL_PIN='export-pin'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(smoke_privacy_agent.Path, "home", lambda: home)

    assert smoke_privacy_agent._approval_pin() == "export-pin"


def test_privacy_smoke_contract_is_synthetic_manual_and_secret_safe() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "set -x" not in text
    assert "bash -x" not in text
    assert "ALPHA_SERVICE_TOKEN" not in text
    assert "echo ${TOKEN}" not in text
    assert 'echo "$TOKEN"' not in text
    assert "curl -v" not in text
    assert "flush=True" in text
    assert "PRIVACY_SMOKE_APPROVAL_PIN" in text
    assert "scripts/gen_test_token.py" in text
    assert "actor_type" not in text
    assert "/v1/privacy/subjects" in text
    assert "/v1/privacy/targets/refresh" in text
    assert "/v1/privacy/case-drafts/{case_id}/submit-approval" in text
    assert "/v1/approvals/unlock" in text
    assert "/v1/approvals/{queue_id}/decide" in text
    assert "/manual-disposition" in text
    assert "/verification" in text
    assert "/timeline" in text
    assert "/report" in text
    assert "outbound_enabled" in text
    assert "privacy-smoke+" in text

    unlock_index = text.index("_unlock_approvals(client, ctx.approval_pin)")
    subject_index = text.index('"/v1/privacy/subjects"')
    assert unlock_index < subject_index
