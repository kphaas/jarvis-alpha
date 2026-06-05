import subprocess

import scripts.rotate_service_token as rotator


def test_verify_brain_uses_postgres_password_from_secrets(tmp_path, monkeypatch):
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text(
        "POSTGRES_PASSWORD=secret-from-file\nALPHA_BUDDY_TOKEN=ignored\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="1", stderr=""
        )

    monkeypatch.setattr(rotator.subprocess, "run", fake_run)

    rotator.verify_brain(str(secrets_file))

    assert seen["args"][:7] == [
        rotator.PSQL_BIN,
        "-h",
        "localhost",
        "-d",
        "jarvis_alpha",
        "-U",
        "jarvisbrain",
    ]
    assert seen["env"]["PGPASSWORD"] == "secret-from-file"
    assert "secret-from-file" not in seen["args"]


def test_verify_brain_prefers_postgres_password_from_env(tmp_path, monkeypatch):
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text("POSTGRES_PASSWORD=secret-from-file\n", encoding="utf-8")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret-from-env")
    seen = {}

    def fake_run(args, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="1", stderr=""
        )

    monkeypatch.setattr(rotator.subprocess, "run", fake_run)

    rotator.verify_brain(str(secrets_file))

    assert seen["env"]["PGPASSWORD"] == "secret-from-env"


def test_alert_failure_brain_uses_authenticated_psql(tmp_path, monkeypatch):
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text("POSTGRES_PASSWORD=secret-from-file\n", encoding="utf-8")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(rotator.subprocess, "run", fake_run)

    rotator.alert_failure("brain", "test failure", None, str(secrets_file))

    assert seen["env"]["PGPASSWORD"] == "secret-from-file"
    assert any("INSERT INTO alpha_buddy_events" in arg for arg in seen["args"])
    assert "secret-from-file" not in seen["args"]


def test_build_rotation_ledger_sql_records_keyturner_service_token_hash():
    sql = rotator.build_rotation_ledger_sql(
        secret_name="ALPHA_SERVICE_TOKEN_ENDPOINT",
        rotation_days=7,
        nodes_updated=["endpoint"],
        services_restarted=["com.jarvis.alpha.endpoint@endpoint"],
        verify_status="passed",
        value_hash="abc123hash",
        rotated_by="keyturner@test",
    )

    assert "INSERT INTO alpha_secret_rotations" in sql
    assert "'ALPHA_SERVICE_TOKEN_ENDPOINT'" in sql
    assert "'keyturner@test'" in sql
    assert "ARRAY['endpoint']::text[]" in sql
    assert "ARRAY['com.jarvis.alpha.endpoint@endpoint']::text[]" in sql
    assert "'passed'" in sql
    assert "'abc123hash'" in sql


def test_record_rotation_ledger_uses_local_psql_for_brain(tmp_path, monkeypatch):
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text("POSTGRES_PASSWORD=secret-from-file\n", encoding="utf-8")
    seen = {}

    def fake_psql(sql, secrets_path):
        seen["sql"] = sql
        seen["secrets_path"] = secrets_path
        return subprocess.CompletedProcess(
            args=["psql"],
            returncode=0,
            stdout="row-id next_due_at=2026-06-12",
            stderr="",
        )

    monkeypatch.setattr(rotator, "run_brain_psql", fake_psql)

    result = rotator.record_rotation_ledger(
        node="brain_service",
        secrets_file=str(secrets_file),
        verify_status="passed",
        value_hash="hash123",
    )

    assert result == "row-id next_due_at=2026-06-12"
    assert seen["secrets_path"] == str(secrets_file)
    assert "'ALPHA_BRAIN_SERVICE_TOKEN'" in seen["sql"]
    assert "ARRAY['brain']::text[]" in seen["sql"]
    assert "ARRAY[]::text[]" in seen["sql"]


def test_record_rotation_ledger_uses_brain_ssh_for_remote_node(monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="remote-row next_due_at=2026-06-12",
            stderr="",
        )

    result = rotator.record_rotation_ledger(
        node="endpoint",
        secrets_file="/ignored",
        verify_status="passed",
        value_hash="hash456",
        runner=fake_run,
    )

    assert result == "remote-row next_due_at=2026-06-12"
    assert seen["args"] == [
        "ssh",
        rotator.BRAIN_SSH_FOR_DB,
        f"{rotator.PSQL_BIN} -d {rotator.PSQL_DB} -U {rotator.PSQL_USER} -t -f -",
    ]
    assert seen["kwargs"]["input"].count("ALPHA_SERVICE_TOKEN_ENDPOINT") == 1
    assert "'endpoint'" in seen["kwargs"]["input"]
    assert "hash456" in seen["kwargs"]["input"]


def test_forge_sentinel_rotation_uses_dedicated_security_token():
    cfg = rotator.NODE_CONFIG["forge_sentinel"]

    assert cfg["iss"] == "forge"
    assert cfg["secret_key"] == "ALPHA_SENTINEL_SERVICE_TOKEN"
    assert cfg["scopes"] == ["security_write"]
    assert (
        rotator.SERVICE_ROTATION_NAMES["forge_sentinel"]
        == "ALPHA_SENTINEL_SERVICE_TOKEN"
    )
    assert rotator.SERVICE_ROTATION_LEDGER_NODES["forge_sentinel"] == "sandbox"
