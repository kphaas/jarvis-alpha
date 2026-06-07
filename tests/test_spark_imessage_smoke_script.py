from pathlib import Path


SCRIPT = Path("scripts/smoke_spark_imessage.sh")


def test_spark_imessage_smoke_script_avoids_secret_tracing() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "set -x" not in text
    assert "bash -x" not in text
    assert "BLUEBUBBLES_PASSWORD" not in text
    assert "echo ${TOKEN}" not in text
    assert 'echo "$TOKEN"' not in text
    assert "curl -v" not in text


def test_spark_imessage_smoke_script_checks_read_only_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert ".venv/bin/python" in text
    assert "SPARK_SMOKE_PYTHON" in text
    assert "/v1/spark/imessage/health" in text
    assert "/v1/spark/imessage/counts" in text
    assert "/v1/spark/imessage/recent-chats/metadata" in text
    assert "/v1/spark/imessage/readiness" in text
    assert "body_access" in text
    assert "raw data array was returned" in text
    assert "chat_guid" in text
    assert "phone_number" in text
