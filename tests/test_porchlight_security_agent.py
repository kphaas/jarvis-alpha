import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import scripts.porchlight_security_agent as porchlight


def _unsigned_jwt(exp: datetime) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": int(exp.timestamp())}).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}."


def test_jwt_live_verification_passes_when_exp_is_far_enough_out():
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    token = _unsigned_jwt(now + timedelta(hours=30))

    status, detail = porchlight._verify_jwt_exp(token, now=now)

    assert status == "passed"
    assert "30.0 hours" in detail


def test_jwt_live_verification_fails_when_expired():
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    token = _unsigned_jwt(now - timedelta(minutes=1))

    status, detail = porchlight._verify_jwt_exp(token, now=now)

    assert status == "failed"
    assert detail == "JWT is expired"


def test_secret_live_verification_fails_for_bad_cloudflare_token(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    config_path = tmp_path / "secrets_rotation.json"
    config_path.write_text(
        json.dumps(
            {
                "secrets": {
                    "CLOUDFLARE_API_TOKEN": {
                        "verify": {"type": "cloudflare_api"},
                        "nodes": ["brain"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_secret(name):
        if name == "CLOUDFLARE_ACCOUNT_ID":
            return "acct-123"
        if name == "CLOUDFLARE_API_TOKEN":
            return "token-abc"
        raise KeyError(name)

    monkeypatch.setattr(porchlight, "get_secret", fake_secret)

    def fake_command(args, timeout=30, input_text=None):
        assert args[-1].endswith("/accounts/acct-123/tokens/verify")
        return porchlight.CommandResult(
            0,
            json.dumps({"success": False, "errors": [{"message": "invalid"}]}),
            "",
        )

    result = porchlight.check_secret_live_verification(
        node_map={},
        config_path=config_path,
        command=fake_command,
    )

    assert result.status == "fail"
    assert result.severity == "critical"
    assert "CLOUDFLARE_API_TOKEN" in result.detail


def test_secret_live_verification_warns_for_stale_gmail_health(tmp_path):
    config_path = tmp_path / "secrets_rotation.json"
    config_path.write_text(
        json.dumps(
            {
                "secrets": {
                    "ALPHA_GMAIL_REFRESH_TOKEN": {
                        "verify": {"type": "gmail_oauth_health"},
                        "nodes": ["brain"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_psql(query):
        assert "alpha_gmail_oauth_health" in query
        return porchlight.CommandResult(0, "ok|2026-06-01 00:00:00+00||\n", "")

    result = porchlight.check_secret_live_verification(
        node_map={},
        config_path=config_path,
        psql=fake_psql,
    )

    assert result.status == "warn"
    assert "ALPHA_GMAIL_REFRESH_TOKEN" in result.detail


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


def test_route_db_access_review_fails_for_unreviewed_route(tmp_path: Path):
    reviewed = {"safe.py": "reviewed test fixture"}
    (tmp_path / "safe.py").write_text(
        "async def route(pool):\n    async with pool.acquire() as conn:\n        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "new_route.py").write_text(
        "async def route(pool):\n    async with pool.acquire() as conn:\n        pass\n",
        encoding="utf-8",
    )

    result = porchlight.check_route_db_access(tmp_path, reviewed)

    assert result.status == "fail"
    assert result.severity == "high"
    assert result.metadata["unreviewed"] == ["new_route.py"]


def test_route_db_access_review_passes_when_reviewed(tmp_path: Path):
    reviewed = {"safe.py": "reviewed test fixture"}
    (tmp_path / "safe.py").write_text(
        "async def route(pool):\n    async with pool.acquire() as conn:\n        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "rls.py").write_text(
        "async def route(request):\n    async with rls_connection(request) as conn:\n        pass\n",
        encoding="utf-8",
    )

    result = porchlight.check_route_db_access(tmp_path, reviewed)

    assert result.status == "pass"
    assert result.metadata["raw_route_files"] == {"safe.py": 1}
    assert result.metadata["uses_rls_helper"] == ["rls.py"]


def test_cloudflare_policy_drift_warns_without_api_credentials(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setattr(
        porchlight, "get_secret", lambda name: (_ for _ in ()).throw(KeyError(name))
    )

    result = porchlight.check_cloudflare_access_policy_drift(
        command=lambda *args, **kwargs: porchlight.CommandResult(
            1, "", "should not run"
        )
    )

    assert result.status == "warn"
    assert result.severity == "medium"


def test_cloudflare_policy_drift_passes_for_email_policy(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
    monkeypatch.setenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS", "family.at-0.com")

    def fake_command(args, timeout=30, input_text=None):
        url = args[-1]
        if url.endswith("/accounts/acct-123/access/apps"):
            return porchlight.CommandResult(
                0,
                porchlight.json.dumps(
                    {
                        "success": True,
                        "result": [
                            {
                                "id": "app-1",
                                "name": "JARVIS Family",
                                "domain": "family.at-0.com",
                            }
                        ],
                    }
                ),
                "",
            )
        if url.endswith("/accounts/acct-123/access/apps/app-1/policies"):
            return porchlight.CommandResult(
                0,
                porchlight.json.dumps(
                    {
                        "success": True,
                        "result": [
                            {
                                "id": "pol-1",
                                "name": "Allowed family users",
                                "decision": "allow",
                                "include": [{"email": {"email": "user@example.com"}}],
                            }
                        ],
                    }
                ),
                "",
            )
        raise AssertionError(url)

    result = porchlight.check_cloudflare_access_policy_drift(command=fake_command)

    assert result.status == "pass"
    assert result.metadata["expected_hosts"] == ["family.at-0.com"]
    assert result.metadata["matched"][0]["name"] == "JARVIS Family"


def test_cloudflare_policy_drift_fails_for_bypass(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
    monkeypatch.setenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS", "family.at-0.com")

    def fake_command(args, timeout=30, input_text=None):
        url = args[-1]
        if url.endswith("/accounts/acct-123/access/apps"):
            return porchlight.CommandResult(
                0,
                porchlight.json.dumps(
                    {
                        "success": True,
                        "result": [
                            {
                                "id": "app-1",
                                "name": "JARVIS Family",
                                "domain": "family.at-0.com",
                                "policies": [
                                    {
                                        "id": "pol-1",
                                        "name": "Bypass",
                                        "decision": "bypass",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                "",
            )
        raise AssertionError(url)

    result = porchlight.check_cloudflare_access_policy_drift(command=fake_command)

    assert result.status == "fail"
    assert result.severity == "critical"
    assert "bypass" in result.detail


def test_cloudflare_audit_logs_warns_on_recent_access_change(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")

    def fake_command(args, timeout=30, input_text=None):
        assert "/accounts/acct-123/logs/audit" in args[-1]
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {
                    "success": True,
                    "result": [
                        {
                            "when": "2026-06-02T15:00:00Z",
                            "actor": {"email": "ken@example.com"},
                            "action": {"type": "update", "result": True},
                            "resource": {"type": "access_application"},
                        }
                    ],
                }
            ),
            "",
        )

    result = porchlight.check_cloudflare_audit_logs(command=fake_command)

    assert result.status == "warn"
    assert result.severity == "medium"
    assert "ken@example.com" in result.detail
