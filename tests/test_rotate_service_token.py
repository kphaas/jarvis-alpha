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
