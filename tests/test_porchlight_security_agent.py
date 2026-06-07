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


def test_jwt_live_verification_uses_configured_threshold():
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    token = _unsigned_jwt(now + timedelta(hours=23))

    status, detail = porchlight._verify_jwt_exp(token, now=now, min_hours=1)

    assert status == "passed"
    assert "23.0 hours" in detail


def test_jwt_live_verification_fails_when_expired():
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    token = _unsigned_jwt(now - timedelta(minutes=1))

    status, detail = porchlight._verify_jwt_exp(token, now=now)

    assert status == "failed"
    assert detail == "JWT is expired"


def test_remote_jwt_verify_uses_restricted_porchlight_command(monkeypatch):
    monkeypatch.setenv("PORCHLIGHT_REMOTE_SSH_ENABLED", "true")
    seen = {}

    def fake_ssh(target, command):
        seen["target"] = target
        seen["command"] = command
        return porchlight.CommandResult(
            0,
            json.dumps({"status": "passed", "detail": "JWT expires in 30.0 hours"}),
            "",
        )

    status, detail = porchlight._remote_jwt_verify(
        "gateway",
        "ALPHA_SERVICE_TOKEN",
        {"gateway": {"ssh_target": "gate@example", "secrets_path": "/ignored"}},
        ssh=fake_ssh,
    )

    assert status == "passed"
    assert detail == "JWT expires in 30.0 hours"
    assert seen == {
        "target": "gate@example",
        "command": "porchlight jwt-exp ALPHA_SERVICE_TOKEN 24",
    }


def test_run_ssh_falls_back_to_explicit_probe_script_on_unrestricted_shell(monkeypatch):
    calls = []

    def fake_command(args, *, timeout=30, **_kwargs):
        calls.append(args)
        if len(calls) == 1:
            return porchlight.CommandResult(
                127, "", "zsh:1: command not found: porchlight"
            )
        return porchlight.CommandResult(0, '{"status":"passed","detail":"ok"}', "")

    monkeypatch.setattr(porchlight, "run_command", fake_command)
    monkeypatch.setattr(porchlight, "ssh_args_for_probe", lambda: ["ssh"])

    result = porchlight.run_ssh(
        "node@example", "porchlight jwt-exp ALPHA_SERVICE_TOKEN 24"
    )

    assert result.returncode == 0
    assert calls == [
        ["ssh", "node@example", "porchlight jwt-exp ALPHA_SERVICE_TOKEN 24"],
        [
            "ssh",
            "node@example",
            "SSH_ORIGINAL_COMMAND='porchlight jwt-exp ALPHA_SERVICE_TOKEN 24' "
            "$HOME/jarvis-alpha/scripts/porchlight_ssh_probe.sh",
        ],
    ]


def test_remote_jwt_verify_uses_configured_threshold(monkeypatch):
    monkeypatch.setenv("PORCHLIGHT_REMOTE_SSH_ENABLED", "true")
    seen = {}

    def fake_ssh(target, command):
        seen["target"] = target
        seen["command"] = command
        return porchlight.CommandResult(
            0,
            json.dumps({"status": "passed", "detail": "JWT expires in 23.0 hours"}),
            "",
        )

    status, detail = porchlight._remote_jwt_verify(
        "endpoint",
        "ALPHA_SERVICE_TOKEN",
        {"endpoint": {"ssh_target": "endpoint@example", "secrets_path": "/ignored"}},
        min_hours=1,
        ssh=fake_ssh,
    )

    assert status == "passed"
    assert detail == "JWT expires in 23.0 hours"
    assert seen == {
        "target": "endpoint@example",
        "command": "porchlight jwt-exp ALPHA_SERVICE_TOKEN 1",
    }


def test_remote_jwt_verify_allows_sentinel_service_token(monkeypatch):
    monkeypatch.setenv("PORCHLIGHT_REMOTE_SSH_ENABLED", "true")
    seen = {}

    def fake_ssh(target, command):
        seen["target"] = target
        seen["command"] = command
        return porchlight.CommandResult(
            0,
            json.dumps({"status": "passed", "detail": "JWT expires in 30.0 hours"}),
            "",
        )

    status, detail = porchlight._remote_jwt_verify(
        "sandbox",
        "ALPHA_SENTINEL_SERVICE_TOKEN",
        {"sandbox": {"ssh_target": "sandbox@example", "secrets_path": "/ignored"}},
        ssh=fake_ssh,
    )

    assert status == "passed"
    assert detail == "JWT expires in 30.0 hours"
    assert seen == {
        "target": "sandbox@example",
        "command": "porchlight jwt-exp ALPHA_SENTINEL_SERVICE_TOKEN 24",
    }


def test_family_smoke_live_verification_authenticates_synthetic_parent(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "secrets_rotation.json"
    config_path.write_text(
        json.dumps(
            {
                "secrets": {
                    "JARVIS_FAMILY_SMOKE_PIN": {
                        "secret_key": "FAMILY_SMOKE_PIN",
                        "verify": {"type": "family_smoke"},
                        "restarts": [
                            {
                                "health_url": "https://family.test/health",
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_secret(name):
        if name == "FAMILY_SMOKE_PIN":
            return "123456"
        raise KeyError(name)

    monkeypatch.setattr(porchlight, "get_secret", fake_secret)

    def fake_command(args, timeout=30, input_text=None):
        if args[-1] == "https://family.test/health":
            return porchlight.CommandResult(0, "200", "")
        if args[-1] == "https://family.test/v1/auth/pin":
            payload = json.loads(args[args.index("-d") + 1])
            assert payload == {"name": "smoke_test_parent", "pin": "123456"}
            return porchlight.CommandResult(
                0,
                json.dumps({"token": "synthetic-token", "role": "parent"}),
                "",
            )
        raise AssertionError(args)

    result = porchlight.check_secret_live_verification(
        node_map={},
        config_path=config_path,
        command=fake_command,
    )

    assert result.status == "pass"
    assert result.metadata["results"]["JARVIS_FAMILY_SMOKE_PIN"] == {
        "status": "passed",
        "detail": "Family smoke auth passed for synthetic parent",
    }


def test_secret_rotation_sets_platform_admin_rls_before_read(tmp_path):
    config_path = tmp_path / "secrets_rotation.json"
    config_path.write_text(
        json.dumps(
            {
                "secrets": {
                    "ALPHA_BRAIN_SERVICE_TOKEN": {
                        "rotation_days": 7,
                        "managed_by": "keyturner",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    seen: dict[str, str] = {}

    def fake_psql(query):
        seen["query"] = query
        return porchlight.CommandResult(
            0,
            "platform_admin\n"
            "ALPHA_BRAIN_SERVICE_TOKEN|2026-06-04|7|2026-06-11|7|skipped\n",
            "",
        )

    result = porchlight.check_secret_rotation(
        psql=fake_psql,
        config_path=config_path,
        today=porchlight.date(2026, 6, 4),
    )

    assert "set_config('rls.role', 'platform_admin', false)" in seen["query"]
    assert result.status == "pass"
    assert "warnings" not in result.metadata
    assert (
        result.metadata["secrets"]["ALPHA_BRAIN_SERVICE_TOKEN"]["last_verify_status"]
        == "skipped"
    )


def test_secret_rotation_warns_inside_cadence_relative_window(tmp_path):
    config_path = tmp_path / "secrets_rotation.json"
    config_path.write_text(
        json.dumps(
            {
                "secrets": {
                    "ALPHA_BRAIN_SERVICE_TOKEN": {
                        "rotation_days": 7,
                        "managed_by": "keyturner",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_psql(query):
        return porchlight.CommandResult(
            0,
            "platform_admin\n"
            "ALPHA_BRAIN_SERVICE_TOKEN|2026-06-04|7|2026-06-11|2|passed\n",
            "",
        )

    result = porchlight.check_secret_rotation(
        psql=fake_psql,
        config_path=config_path,
        today=porchlight.date(2026, 6, 9),
    )

    assert result.status == "warn"
    assert result.metadata["warnings"] == ["ALPHA_BRAIN_SERVICE_TOKEN due in 2 days"]


def test_family_external_smoke_live_verification_authenticates_synthetic_external(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "secrets_rotation.json"
    config_path.write_text(
        json.dumps(
            {
                "secrets": {
                    "JARVIS_FAMILY_EXTERNAL_SMOKE_PIN": {
                        "secret_key": "FAMILY_EXTERNAL_SMOKE_PIN",
                        "verify": {"type": "family_external_smoke"},
                        "restarts": [
                            {
                                "health_url": "https://family.test/health",
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fake_secret(name):
        if name == "FAMILY_EXTERNAL_SMOKE_PIN":
            return "654321"
        raise KeyError(name)

    monkeypatch.setattr(porchlight, "get_secret", fake_secret)

    def fake_command(args, timeout=30, input_text=None):
        if args[-1] == "https://family.test/health":
            return porchlight.CommandResult(0, "200", "")
        if args[-1] == "https://family.test/v1/auth/pin":
            payload = json.loads(args[args.index("-d") + 1])
            assert payload == {"name": "smoke_test_external", "pin": "654321"}
            return porchlight.CommandResult(
                0,
                json.dumps({"token": "synthetic-token", "role": "external"}),
                "",
            )
        raise AssertionError(args)

    result = porchlight.check_secret_live_verification(
        node_map={},
        config_path=config_path,
        command=fake_command,
    )

    assert result.status == "pass"
    assert result.metadata["results"]["JARVIS_FAMILY_EXTERNAL_SMOKE_PIN"] == {
        "status": "passed",
        "detail": "Family smoke auth passed for synthetic external",
    }


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
                    "127\t0\tcom.jarvis.alpha.sweep-cert-renewal.brain",
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


def test_route_db_access_default_allowlist_has_no_stale_entries():
    result = porchlight.check_route_db_access()

    assert result.metadata["stale_reviews"] == []


def test_postgres_role_safety_fails_when_jarvisbrain_is_only_superuser():
    def fake_psql(query):
        assert "FROM pg_roles" in query
        return porchlight.CommandResult(
            0,
            "\n".join(
                [
                    "jarvis_alpha_app|false|false|false|false|false|16388",
                    "jarvis_alpha_writer|false|false|false|false|false|16389",
                    "jarvisbrain|true|false|true|true|true|10",
                ]
            ),
            "",
        )

    result = porchlight.check_postgres_role_safety(psql=fake_psql)

    assert result.status == "fail"
    assert result.severity == "critical"
    assert "break-glass" in result.detail
    assert result.metadata["superusers"] == ["jarvisbrain"]


def test_postgres_role_safety_warns_when_bootstrap_superuser_is_contained():
    def fake_psql(query):
        if "FROM pg_roles" in query:
            return porchlight.CommandResult(
                0,
                "\n".join(
                    [
                        "jarvis_alpha_app|false|false|false|false|false|16388",
                        "jarvis_alpha_owner|false|false|false|false|false|16390",
                        "jarvis_alpha_writer|false|false|false|false|false|16389",
                        "jarvis_pg_breakglass|true|false|true|true|true|24576",
                        "jarvisbrain|true|false|true|true|true|10",
                    ]
                ),
                "",
            )
        if "FROM pg_proc" in query:
            return porchlight.CommandResult(
                0,
                "\n".join(
                    [
                        "public.record_buddy_event(p_user_id text, p_event_type text, p_title text, p_body text, p_priority integer, p_source text, p_payload jsonb)|jarvis_alpha_owner|plpgsql",
                        "public.pgaudit_sql_drop()|jarvisbrain|c",
                    ]
                ),
                "",
            )
        raise AssertionError(query)

    result = porchlight.check_postgres_role_safety(psql=fake_psql)

    assert result.status == "warn"
    assert result.severity == "medium"
    assert result.metadata["bootstrap_risk"] == "accepted_contained"
    assert result.metadata["accepted_exception"] == "postgres_bootstrap_role_superuser"
    assert result.metadata["security_definer"]["owner_counts"] == {
        "jarvis_alpha_owner": 1,
        "jarvisbrain": 1,
    }


def test_postgres_role_safety_fails_when_secdef_owner_split_drifts():
    def fake_psql(query):
        if "FROM pg_roles" in query:
            return porchlight.CommandResult(
                0,
                "\n".join(
                    [
                        "jarvis_alpha_app|false|false|false|false|false|16388",
                        "jarvis_alpha_owner|false|false|false|false|false|16390",
                        "jarvis_alpha_writer|false|false|false|false|false|16389",
                        "jarvis_pg_breakglass|true|false|true|true|true|24576",
                        "jarvisbrain|true|false|true|true|true|10",
                    ]
                ),
                "",
            )
        if "FROM pg_proc" in query:
            return porchlight.CommandResult(
                0,
                "public.record_buddy_event(p_user_id text)|jarvisbrain|plpgsql",
                "",
            )
        raise AssertionError(query)

    result = porchlight.check_postgres_role_safety(psql=fake_psql)

    assert result.status == "fail"
    assert result.severity == "critical"
    assert "unexpected SECURITY DEFINER owner" in result.detail


def test_postgres_role_safety_fails_when_runtime_role_bypasses_rls():
    def fake_psql(query):
        return porchlight.CommandResult(
            0,
            "\n".join(
                [
                    "breakglass_admin|true|false|true|true|true|24576",
                    "jarvis_alpha_app|false|false|false|false|false|16388",
                    "jarvis_alpha_writer|false|true|false|false|false|16389",
                    "jarvisbrain|false|false|true|true|true|10",
                ]
            ),
            "",
        )

    result = porchlight.check_postgres_role_safety(psql=fake_psql)

    assert result.status == "fail"
    assert result.severity == "critical"
    assert result.metadata["runtime_bypass_roles"] == ["jarvis_alpha_writer"]


def test_postgres_role_safety_warns_for_bootstrap_exception_with_breakglass():
    def fake_psql(query):
        if "FROM pg_proc" in query:
            return porchlight.CommandResult(
                0,
                "public.record_buddy_event(p_user_id text)|jarvis_alpha_owner|plpgsql",
                "",
            )
        return porchlight.CommandResult(
            0,
            "\n".join(
                [
                    "jarvis_alpha_app|false|false|false|false|false|16388",
                    "jarvis_alpha_owner|false|false|false|false|false|16390",
                    "jarvis_alpha_writer|false|false|false|false|false|16389",
                    "jarvis_pg_breakglass|true|false|true|true|true|24576",
                    "jarvisbrain|true|false|true|true|true|10",
                ]
            ),
            "",
        )

    result = porchlight.check_postgres_role_safety(psql=fake_psql)

    assert result.status == "warn"
    assert result.severity == "medium"
    assert result.metadata["accepted_exception"] == "postgres_bootstrap_role_superuser"
    assert result.metadata["bootstrap_risk"] == "accepted_contained"
    assert result.metadata["superusers"] == ["jarvis_pg_breakglass", "jarvisbrain"]
    assert "bootstrap superuser" in result.summary


def test_postgres_role_safety_fails_for_non_bootstrap_jarvisbrain_superuser():
    def fake_psql(query):
        return porchlight.CommandResult(
            0,
            "\n".join(
                [
                    "breakglass_admin|true|false|true|true|true|24576",
                    "jarvis_alpha_app|false|false|false|false|false|16388",
                    "jarvis_alpha_writer|false|false|false|false|false|16389",
                    "jarvisbrain|true|false|true|true|true|16390",
                ]
            ),
            "",
        )

    result = porchlight.check_postgres_role_safety(psql=fake_psql)

    assert result.status == "fail"
    assert result.severity == "critical"
    assert "not the bootstrap role" in result.detail


def test_postgres_role_safety_passes_with_breakglass_and_demoted_jarvisbrain():
    def fake_psql(query):
        return porchlight.CommandResult(
            0,
            "\n".join(
                [
                    "breakglass_admin|true|false|true|true|true|24576",
                    "jarvis_alpha_app|false|false|false|false|false|16388",
                    "jarvis_alpha_writer|false|false|false|false|false|16389",
                    "jarvisbrain|false|false|true|true|true|10",
                ]
            ),
            "",
        )

    result = porchlight.check_postgres_role_safety(psql=fake_psql)

    assert result.status == "pass"
    assert result.metadata["superusers"] == ["breakglass_admin"]


def test_postgres_hba_safety_fails_on_broad_local_trust():
    def fake_psql(query):
        assert "FROM pg_hba_file_rules" in query
        return porchlight.CommandResult(
            0,
            "\n".join(
                [
                    "90|local|all|all||trust|",
                    "92|host|all|all|127.0.0.1|trust|",
                    "94|host|replication|all|127.0.0.1|trust|",
                ]
            ),
            "",
        )

    result = porchlight.check_postgres_hba_safety(psql=fake_psql)

    assert result.status == "fail"
    assert result.severity == "critical"
    assert "broad local trust auth" in result.detail
    assert result.metadata["trust_rule_count"] == 3
    assert len(result.metadata["broad_trust_rules"]) == 2


def test_postgres_hba_safety_fails_on_parser_error():
    def fake_psql(query):
        return porchlight.CommandResult(
            0,
            "90|local|all|all||scram-sha-256|invalid authentication method",
            "",
        )

    result = porchlight.check_postgres_hba_safety(psql=fake_psql)

    assert result.status == "fail"
    assert result.severity == "critical"
    assert "pg_hba parse errors" in result.detail


def test_postgres_hba_safety_passes_without_broad_trust():
    def fake_psql(query):
        return porchlight.CommandResult(
            0,
            "\n".join(
                [
                    "90|local|all|all||scram-sha-256|",
                    "92|host|all|all|127.0.0.1|scram-sha-256|",
                    "94|host|all|all|::1|scram-sha-256|",
                    "96|local|replication|postgres||peer|",
                ]
            ),
            "",
        )

    result = porchlight.check_postgres_hba_safety(psql=fake_psql)

    assert result.status == "pass"
    assert result.metadata["trust_rule_count"] == 0


def test_run_psql_uses_password_auth_for_local_jarvisbrain(monkeypatch):
    captured = {}

    def fake_run_command(args, timeout=30, input_text=None, env=None):
        captured["args"] = args
        captured["input_text"] = input_text
        captured["env"] = env
        return porchlight.CommandResult(0, "ok", "")

    monkeypatch.setenv("JARVIS_NODE", "brain")
    monkeypatch.setenv("POSTGRES_PASSWORD", "postgres-secret")
    monkeypatch.setattr(porchlight, "PSQL_USER", "jarvisbrain")
    monkeypatch.setattr(porchlight, "run_command", fake_run_command)

    result = porchlight.run_psql("SELECT 1;")

    assert result.returncode == 0
    assert captured["input_text"] == "SELECT 1;"
    assert captured["args"][1:3] == ["-h", "localhost"]
    assert "postgres-secret" not in captured["args"]
    assert captured["env"]["PGPASSWORD"] == "postgres-secret"


def test_run_psql_remote_sources_brain_secret_without_embedding_password(monkeypatch):
    captured = {}

    def fake_run_command(args, timeout=30, input_text=None, env=None):
        captured["args"] = args
        captured["input_text"] = input_text
        captured["env"] = env
        return porchlight.CommandResult(0, "ok", "")

    monkeypatch.delenv("JARVIS_NODE", raising=False)
    monkeypatch.setattr(porchlight, "_postgres_password", lambda: None)
    monkeypatch.setattr(porchlight.socket, "gethostname", lambda: "macbook-air")
    monkeypatch.setattr(porchlight, "PSQL_USER", "jarvisbrain")
    monkeypatch.setattr(porchlight, "run_command", fake_run_command)

    result = porchlight.run_psql("SELECT 1;")

    assert result.returncode == 0
    remote_command = captured["args"][-1]
    assert "source ~/jarvis/.secrets" in remote_command
    assert 'PGPASSWORD="$POSTGRES_PASSWORD"' in remote_command
    assert " -h localhost " in remote_command
    assert "postgres-secret" not in remote_command
    assert captured["env"] is None


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


def test_cloudflare_policy_drift_warns_when_exact_membership_unconfigured(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
    monkeypatch.setenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS", "family.at-0.com")
    monkeypatch.delenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS", raising=False)

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

    assert result.status == "warn"
    assert result.severity == "medium"
    assert "exact policy membership" in result.summary
    assert result.metadata["expected_hosts"] == ["family.at-0.com"]
    assert result.metadata["matched"][0]["name"] == "JARVIS Family"
    assert result.metadata["expected_policy_emails_count"] == 0
    assert result.metadata["matched_policy_emails_count"] == 1


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


def test_cloudflare_policy_drift_fails_for_email_domain_rule(monkeypatch):
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
                                        "name": "Domain allow",
                                        "decision": "allow",
                                        "include": [
                                            {"email_domain": {"domain": "example.com"}}
                                        ],
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
    assert "email_domain" in result.detail


def test_cloudflare_policy_drift_enforces_exact_expected_membership(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
    monkeypatch.setenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS", "family.at-0.com")
    monkeypatch.setenv(
        "PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS",
        "ken@example.com, meagan@example.com",
    )

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
                                "include": [
                                    {"email": {"email": "ken@example.com"}},
                                    {"email": {"email": "meagan@example.com"}},
                                ],
                            }
                        ],
                    }
                ),
                "",
            )
        raise AssertionError(url)

    result = porchlight.check_cloudflare_access_policy_drift(command=fake_command)

    assert result.status == "pass"
    assert result.metadata["expected_policy_emails_count"] == 2
    assert result.metadata["matched_policy_emails_count"] == 2


def test_cloudflare_policy_drift_loads_expected_membership_from_secret(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
    monkeypatch.setenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS", "family.at-0.com")
    monkeypatch.delenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS", raising=False)

    def fake_secret(name: str) -> str:
        if name == "PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS":
            return "ken@example.com, meagan@example.com"
        raise KeyError(name)

    monkeypatch.setattr(porchlight, "get_secret", fake_secret)

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
                                "include": [
                                    {"email": {"email": "ken@example.com"}},
                                    {"email": {"email": "meagan@example.com"}},
                                ],
                            }
                        ],
                    }
                ),
                "",
            )
        raise AssertionError(url)

    result = porchlight.check_cloudflare_access_policy_drift(command=fake_command)

    assert result.status == "pass"
    assert result.metadata["expected_policy_emails_count"] == 2
    assert result.metadata["matched_policy_emails_count"] == 2


def test_cloudflare_policy_drift_fails_for_unexpected_family_member(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
    monkeypatch.setenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS", "family.at-0.com")
    monkeypatch.setenv(
        "PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS",
        "ken@example.com, meagan@example.com",
    )

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
                                        "name": "Allowed family users",
                                        "decision": "allow",
                                        "include": [
                                            {"email": {"email": "ken@example.com"}},
                                            {
                                                "email": {
                                                    "email": "stranger@example.com"
                                                }
                                            },
                                        ],
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
    assert "missing expected email" in result.detail
    assert "unexpected email" in result.detail


def test_cloudflare_policy_drift_blocks_everyone_rule(monkeypatch):
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
                                        "name": "Everyone",
                                        "decision": "allow",
                                        "include": [{"everyone": {}}],
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
    assert "everyone" in result.detail


def test_cloudflare_policy_drift_fails_for_alpha_or_brain_public_app(monkeypatch):
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
                                        "name": "Allowed family users",
                                        "decision": "allow",
                                        "include": [
                                            {"email": {"email": "ken@example.com"}}
                                        ],
                                    }
                                ],
                            },
                            {
                                "id": "app-2",
                                "name": "JARVIS Alpha",
                                "domain": "alpha.at-0.com",
                                "policies": [
                                    {
                                        "id": "pol-2",
                                        "name": "Allowed users",
                                        "decision": "allow",
                                        "include": [
                                            {"email": {"email": "ken@example.com"}}
                                        ],
                                    }
                                ],
                            },
                        ],
                    }
                ),
                "",
            )
        raise AssertionError(url)

    result = porchlight.check_cloudflare_access_policy_drift(command=fake_command)

    assert result.status == "fail"
    assert result.severity == "critical"
    assert "Alpha/Brain" in result.summary
    assert "alpha.at-0.com" in result.detail


def test_cloudflare_audit_logs_passes_on_expected_actor_change(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-abc")
    monkeypatch.setenv("PORCHLIGHT_CLOUDFLARE_EXPECTED_ACTORS", "ken@example.com")

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

    assert result.status == "pass"
    assert result.summary.startswith("Only expected Cloudflare")


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


def test_dependency_cve_scan_fails_on_high_npm_vuln(tmp_path, monkeypatch):
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    (ui_dir / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(porchlight, "PYTHON_REQUIREMENTS", tuple())
    monkeypatch.setattr(porchlight, "UI_DIR", ui_dir)

    def fake_command(args, **kwargs):
        assert args[0] == porchlight.NPM_BIN
        assert args[1] == "audit"
        if Path(porchlight.NPM_BIN).is_absolute():
            assert str(Path(porchlight.NPM_BIN).parent) in kwargs["env"]["PATH"]
        return porchlight.CommandResult(
            1,
            porchlight.json.dumps(
                {
                    "vulnerabilities": {
                        "bad-package": {"severity": "high"},
                        "low-package": {"severity": "low"},
                    }
                }
            ),
            "",
        )

    result = porchlight.check_dependency_cve_scan(command=fake_command)

    assert result.status == "fail"
    assert result.severity == "high"
    assert result.metadata["counts"]["high"] == 1


def test_dependency_cve_scan_warns_when_scanner_missing(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("fastapi\n", encoding="utf-8")
    monkeypatch.setattr(porchlight, "PYTHON_REQUIREMENTS", (requirements,))
    monkeypatch.setattr(porchlight, "UI_DIR", tmp_path / "ui")

    result = porchlight.check_dependency_cve_scan(
        command=lambda *args, **kwargs: porchlight.CommandResult(
            1, "", "No module named pip_audit"
        )
    )

    assert result.status == "warn"
    assert "could not run" in result.summary


def test_financial_security_posture_warns_when_unconfigured(monkeypatch):
    monkeypatch.delenv("JARVIS_FIN_SECURITY_POSTURE_TOKEN", raising=False)
    monkeypatch.delenv("FINANCIAL_SECURITY_POSTURE_TOKEN", raising=False)

    result = porchlight.check_financial_security_posture(url="")

    assert result.status == "warn"
    assert result.severity == "medium"
    assert result.metadata["configured"] is False


def test_financial_security_posture_url_prefers_env(monkeypatch):
    monkeypatch.setenv(
        "PORCHLIGHT_FINANCIAL_SECURITY_POSTURE_URL",
        "https://financial-env.example.test/monitor/security-posture",
    )
    monkeypatch.setattr(
        porchlight,
        "get_secret",
        lambda _name: "https://financial-secret.example.test/monitor/security-posture",
    )

    assert (
        porchlight._financial_security_posture_url()
        == "https://financial-env.example.test/monitor/security-posture"
    )


def test_financial_security_posture_url_loads_from_secret(monkeypatch):
    monkeypatch.delenv("PORCHLIGHT_FINANCIAL_SECURITY_POSTURE_URL", raising=False)
    monkeypatch.delenv("FINANCIAL_SECURITY_POSTURE_URL", raising=False)

    def fake_get_secret(name):
        if name == "PORCHLIGHT_FINANCIAL_SECURITY_POSTURE_URL":
            return "https://financial-secret.example.test/monitor/security-posture"
        raise RuntimeError(name)

    monkeypatch.setattr(porchlight, "get_secret", fake_get_secret)

    assert (
        porchlight._financial_security_posture_url()
        == "https://financial-secret.example.test/monitor/security-posture"
    )


def test_financial_security_posture_passes_sanitized_response(monkeypatch):
    monkeypatch.setenv("JARVIS_FIN_SECURITY_POSTURE_TOKEN", "3" * 64)

    def fake_command(args, **kwargs):
        assert "Authorization: Bearer " + ("3" * 64) in args
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {
                    "service": "jarvis-financial",
                    "status": "pass",
                    "counts": {"pass": 7, "warn": 0, "fail": 0},
                    "controls": [
                        {
                            "id": "db.rls_coverage",
                            "status": "pass",
                            "severity": "info",
                            "summary": "All public tables protected.",
                            "metadata": {"secret": "must-not-copy"},
                        }
                    ],
                }
            )
            + "\n200",
            "",
        )

    result = porchlight.check_financial_security_posture(
        url="https://financial.example.test/monitor/security-posture",
        command=fake_command,
    )

    assert result.status == "pass"
    assert result.detail == "7 pass, 0 warn, 0 fail"
    assert result.metadata["controls"] == [
        {"id": "db.rls_coverage", "status": "pass", "severity": "info"}
    ]
    assert "must-not-copy" not in porchlight.json.dumps(result.metadata)


def test_financial_security_posture_fails_on_remote_fail(monkeypatch):
    monkeypatch.setenv("JARVIS_FIN_SECURITY_POSTURE_TOKEN", "3" * 64)

    def fake_command(args, **kwargs):
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {
                    "service": "jarvis-financial",
                    "status": "fail",
                    "counts": {"pass": 5, "warn": 1, "fail": 1},
                    "controls": [],
                }
            )
            + "\n200",
            "",
        )

    result = porchlight.check_financial_security_posture(
        url="https://financial.example.test/monitor/security-posture",
        command=fake_command,
    )

    assert result.status == "fail"
    assert result.severity == "high"
    assert result.detail == "5 pass, 1 warn, 1 fail"


def test_github_branch_protection_drift_passes(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv(
        "PORCHLIGHT_GITHUB_BRANCH_PROTECTION_REPOS", "kphaas/jarvis-alpha"
    )
    monkeypatch.setenv("PORCHLIGHT_GITHUB_REQUIRED_CHECKS", "tests")

    def fake_command(args, **kwargs):
        assert args[-1].endswith("/repos/kphaas/jarvis-alpha/branches/main/protection")
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {
                    "required_pull_request_reviews": {
                        "required_approving_review_count": 1,
                        "dismiss_stale_reviews": True,
                        "require_last_push_approval": True,
                    },
                    "required_status_checks": {"strict": True, "contexts": ["tests"]},
                }
            ),
            "",
        )

    result = porchlight.check_github_branch_protection_drift(command=fake_command)

    assert result.status == "pass"


def test_github_branch_protection_drift_fails_without_pr_reviews(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv(
        "PORCHLIGHT_GITHUB_BRANCH_PROTECTION_REPOS", "kphaas/jarvis-alpha"
    )

    def fake_command(args, **kwargs):
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {"required_status_checks": {"strict": True, "contexts": ["tests"]}}
            ),
            "",
        )

    result = porchlight.check_github_branch_protection_drift(command=fake_command)

    assert result.status == "fail"
    assert "missing PR-review" in result.detail


def test_github_branch_protection_default_repos_and_checks_are_strict(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.delenv("PORCHLIGHT_GITHUB_BRANCH_PROTECTION_REPOS", raising=False)
    monkeypatch.delenv("PORCHLIGHT_GITHUB_REQUIRED_CHECKS", raising=False)
    seen_urls = []

    def fake_command(args, **kwargs):
        seen_urls.append(args[-1])
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {
                    "required_pull_request_reviews": {
                        "required_approving_review_count": 1,
                        "dismiss_stale_reviews": True,
                        "require_last_push_approval": True,
                    },
                    "required_status_checks": {
                        "strict": True,
                        "contexts": sorted(porchlight.DEFAULT_GITHUB_REQUIRED_CHECKS),
                    },
                }
            ),
            "",
        )

    result = porchlight.check_github_branch_protection_drift(command=fake_command)

    assert result.status == "pass"
    assert result.metadata["required_checks"] == sorted(
        porchlight.DEFAULT_GITHUB_REQUIRED_CHECKS
    )
    assert seen_urls == [
        "https://api.github.com/repos/kphaas/jarvis-alpha/branches/main/protection",
        "https://api.github.com/repos/kphaas/jarvis-financial/branches/main/protection",
        "https://api.github.com/repos/kphaas/jarvis-forge/branches/main/protection",
    ]


def test_github_branch_protection_drift_fails_when_reviews_are_weak(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv(
        "PORCHLIGHT_GITHUB_BRANCH_PROTECTION_REPOS", "kphaas/jarvis-alpha"
    )
    monkeypatch.setenv("PORCHLIGHT_GITHUB_REQUIRED_CHECKS", "tests")

    def fake_command(args, **kwargs):
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {
                    "required_pull_request_reviews": {
                        "required_approving_review_count": 0,
                        "dismiss_stale_reviews": False,
                        "require_last_push_approval": False,
                    },
                    "required_status_checks": {"strict": False, "contexts": ["tests"]},
                }
            ),
            "",
        )

    result = porchlight.check_github_branch_protection_drift(command=fake_command)

    assert result.status == "fail"
    assert "requires no approving review" in result.detail
    assert "does not dismiss stale reviews" in result.detail
    assert "does not require last-push approval" in result.detail
    assert "does not require up-to-date branches" in result.detail


def test_notification_filter_suppresses_routine_rotation_warning():
    report = porchlight.build_report(
        [
            porchlight.CheckResult(
                name="secret_rotation",
                status="warn",
                severity="medium",
                summary="Secret rotation has upcoming/manual items to review.",
                detail="ALPHA_BUDDY_TOKEN due in 7 days",
            )
        ]
    )

    assert porchlight.has_notifiable_security_condition(report) is False


def test_backup_recovery_passes_with_recent_restore_and_notification(monkeypatch):
    monkeypatch.setattr(porchlight, "remote_ssh_probe_enabled", lambda: True)
    monkeypatch.setattr(porchlight, "current_node_name", lambda: "brain")

    def fake_ssh(target, command):
        assert target == "jarvissand@example"
        assert command == "porchlight restore-drill-status"
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {
                    "path": "/Users/jarvissand/jarvis/logs/restore_drill.json",
                    "report_mtime": "2026-06-05T17:00:00+00:00",
                    "run_id": "2026-06-05_170000",
                    "status": "pass",
                    "source_dump": "jarvis_alpha.dump.gpg",
                    "restore_rc": 1,
                    "restore_err_count": 2,
                    "pgaudit_err_count": 2,
                    "table_count": 77,
                    "ref_table_count": 77,
                    "notification": {"event": "mm_notify_sent", "http_code": "200"},
                }
            ),
            "",
        )

    result = porchlight.check_backup_recovery(
        node_map={"sandbox": {"ssh_target": "jarvissand@example"}},
        ssh=fake_ssh,
        now=porchlight.datetime(2026, 6, 5, 18, 0, tzinfo=porchlight.UTC),
    )

    assert result.status == "pass"
    assert result.metadata["age_hours"] == 1.0
    assert result.metadata["notification"]["event"] == "mm_notify_sent"


def test_backup_recovery_warns_when_notification_proof_missing(monkeypatch):
    monkeypatch.setattr(porchlight, "remote_ssh_probe_enabled", lambda: True)
    monkeypatch.setattr(porchlight, "current_node_name", lambda: "brain")

    def fake_ssh(_target, _command):
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {
                    "report_mtime": "2026-06-05T17:00:00+00:00",
                    "run_id": "2026-06-05_170000",
                    "status": "pass",
                    "source_dump": "jarvis_alpha.dump.gpg",
                    "notification": {"event": "unknown"},
                }
            ),
            "",
        )

    result = porchlight.check_backup_recovery(
        node_map={"sandbox": {"ssh_target": "jarvissand@example"}},
        ssh=fake_ssh,
        now=porchlight.datetime(2026, 6, 5, 18, 0, tzinfo=porchlight.UTC),
    )

    assert result.status == "warn"
    assert "notification proof" in result.summary


def test_backup_recovery_fails_when_latest_restore_is_stale(monkeypatch):
    monkeypatch.setattr(porchlight, "remote_ssh_probe_enabled", lambda: True)
    monkeypatch.setattr(porchlight, "current_node_name", lambda: "brain")

    def fake_ssh(_target, _command):
        return porchlight.CommandResult(
            0,
            porchlight.json.dumps(
                {
                    "report_mtime": "2026-05-20T17:00:00+00:00",
                    "run_id": "2026-05-20_170000",
                    "status": "pass",
                    "source_dump": "jarvis_alpha.dump.gpg",
                    "notification": {"event": "mm_notify_sent", "http_code": "200"},
                }
            ),
            "",
        )

    result = porchlight.check_backup_recovery(
        node_map={"sandbox": {"ssh_target": "jarvissand@example"}},
        ssh=fake_ssh,
        now=porchlight.datetime(2026, 6, 5, 18, 0, tzinfo=porchlight.UTC),
        max_age_hours=192,
    )

    assert result.status == "fail"
    assert result.severity == "high"


def test_notification_filter_suppresses_accepted_bootstrap_role_warning():
    report = porchlight.build_report(
        [
            porchlight.CheckResult(
                name="postgres_role_safety",
                status="warn",
                severity="medium",
                summary="Postgres bootstrap superuser risk is accepted and contained.",
                metadata={
                    "accepted_exception": "postgres_bootstrap_role_superuser",
                    "bootstrap_risk": "accepted_contained",
                },
            )
        ]
    )

    assert porchlight.has_notifiable_security_condition(report) is False
    assert porchlight.agent_event_severity(report) == "info"


def test_notification_filter_keeps_unexpected_warning():
    report = porchlight.build_report(
        [
            porchlight.CheckResult(
                name="cloudflare_audit_logs",
                status="warn",
                severity="medium",
                summary="Unexpected Cloudflare Access changes occurred.",
            )
        ]
    )

    assert porchlight.has_notifiable_security_condition(report) is True


def test_main_records_non_notifying_status_event_for_non_notifiable_warning(
    monkeypatch, tmp_path
):
    report = porchlight.build_report(
        [
            porchlight.CheckResult(
                name="postgres_role_safety",
                status="warn",
                severity="medium",
                summary="Postgres bootstrap superuser risk is accepted and contained.",
                metadata={
                    "accepted_exception": "postgres_bootstrap_role_superuser",
                    "bootstrap_risk": "accepted_contained",
                },
            )
        ]
    )
    recorded: list[str] = []

    monkeypatch.setattr(porchlight, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(
        porchlight,
        "parse_args",
        lambda: porchlight.argparse.Namespace(
            json=False,
            always_report=False,
            report_warnings=False,
            no_buddy_event=False,
            strict=False,
            max_token_log_age_hours=36,
            cloudflare_access_url="",
            cloudflare_audit_window_hours=24,
        ),
    )
    monkeypatch.setattr(porchlight, "run_sweep", lambda _args: report)
    monkeypatch.setattr(
        porchlight,
        "record_agent_event",
        lambda _report, *, notification_status, psql=porchlight.run_psql: (
            recorded.append(notification_status)
            or porchlight.CommandResult(0, "event-id", "")
        ),
    )

    assert porchlight.main() == 0
    assert recorded == ["not_requested"]
