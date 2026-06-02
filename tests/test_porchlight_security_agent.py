from datetime import UTC, datetime

import scripts.porchlight_security_agent as porchlight


def test_security_launchagents_warns_when_remote_probe_not_configured(monkeypatch):
    monkeypatch.setenv("JARVIS_NODE", "brain")
    monkeypatch.delenv("PORCHLIGHT_REMOTE_SSH_ENABLED", raising=False)
    monkeypatch.delenv("PORCHLIGHT_SSH_KEY", raising=False)
    monkeypatch.setattr(
        porchlight, "DEFAULT_PORCHLIGHT_SSH_KEY", porchlight.Path("/missing/key")
    )

    def fake_run_command(args, timeout=30, input_text=None):
        assert args == ["launchctl", "list"]
        return porchlight.CommandResult(
            0,
            "\n".join(
                [
                    "123\t0\tcom.jarvis.alpha.rotate.brain_service",
                    "124\t0\tcom.jarvis.alpha.rotate.buddy",
                    "125\t0\tcom.jarvis.alpha.pg_backup",
                    "126\t0\tcom.jarvis.alpha.gmail-health",
                ]
            ),
            "",
        )

    monkeypatch.setattr(porchlight, "run_command", fake_run_command)

    result = porchlight.check_security_launchagents(
        node_map={
            "endpoint": {"ssh_target": "endpoint"},
            "gateway": {"ssh_target": "gateway"},
            "sandbox": {"ssh_target": "sandbox"},
        },
        ssh=lambda target, command: porchlight.CommandResult(1, "", "should not run"),
    )

    assert result.status == "warn"
    assert result.metadata["skipped_remote"] == {
        "endpoint": "remote SSH probe not configured",
        "gateway": "remote SSH probe not configured",
        "sandbox": "remote SSH probe not configured",
    }
    assert "brain" in result.metadata["loaded_by_node"]


def test_token_rotation_logs_warns_when_remote_probe_not_configured(monkeypatch):
    now = datetime(2026, 6, 2, 13, 0, tzinfo=UTC)
    monkeypatch.setenv("JARVIS_NODE", "brain")
    monkeypatch.delenv("PORCHLIGHT_REMOTE_SSH_ENABLED", raising=False)
    monkeypatch.delenv("PORCHLIGHT_SSH_KEY", raising=False)
    monkeypatch.setattr(
        porchlight, "DEFAULT_PORCHLIGHT_SSH_KEY", porchlight.Path("/missing/key")
    )

    def fake_run_command(args, timeout=30, input_text=None):
        assert args == ["/bin/sh", "-lc", porchlight.TOKEN_LOG_COMMAND]
        return porchlight.CommandResult(
            0,
            "\n".join(
                [
                    '{"timestamp":"2026-06-02T12:00:00+00:00","node":"brain","message":"rotation complete"}',
                    '{"timestamp":"2026-06-02T12:05:00+00:00","node":"brain_service","message":"rotation skipped"}',
                ]
            ),
            "",
        )

    monkeypatch.setattr(porchlight, "run_command", fake_run_command)

    result = porchlight.check_token_rotation_logs(
        node_map={
            "endpoint": {"ssh_target": "endpoint"},
            "gateway": {"ssh_target": "gateway"},
            "sandbox": {"ssh_target": "sandbox"},
        },
        ssh=lambda target, command: porchlight.CommandResult(1, "", "should not run"),
        now=now,
    )

    assert result.status == "warn"
    assert result.metadata["recent"] == {
        "brain": "2026-06-02T12:00:00+00:00",
        "brain_service": "2026-06-02T12:05:00+00:00",
    }
    assert result.metadata["skipped_remote"] == {
        "endpoint": "remote SSH probe not configured",
        "gateway": "remote SSH probe not configured",
        "sandbox": "remote SSH probe not configured",
    }


def test_remote_probe_enabled_when_default_key_exists(monkeypatch):
    monkeypatch.setenv("JARVIS_NODE", "brain")
    monkeypatch.delenv("PORCHLIGHT_REMOTE_SSH_ENABLED", raising=False)
    monkeypatch.delenv("PORCHLIGHT_SSH_KEY", raising=False)

    class FakePath:
        def is_file(self):
            return True

    monkeypatch.setattr(porchlight, "DEFAULT_PORCHLIGHT_SSH_KEY", FakePath())

    assert porchlight.remote_ssh_probe_enabled() is True
