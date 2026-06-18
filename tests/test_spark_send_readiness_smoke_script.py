from pathlib import Path


SCRIPT = Path("scripts/smoke_spark_send_readiness.sh")


def test_spark_send_readiness_smoke_script_avoids_secret_tracing() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "set -x" not in text
    assert "bash -x" not in text
    assert "BLUEBUBBLES_PASSWORD" not in text
    assert "echo ${TOKEN}" not in text
    assert "echo \"$TOKEN\"" not in text
    assert "curl -v" not in text
    assert "trap 'rm -rf \"${TMP_DIR}\"' EXIT" in text


def test_spark_send_readiness_smoke_script_is_non_live_canary() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert ".venv/bin/python" in text
    assert "SPARK_SMOKE_PYTHON" in text
    assert "spark.draft,imessage.read,admin" in text
    assert "imessage.send" not in text
    assert "/v1/spark/imessage/readiness" in text
    assert "/v1/spark/drafts/imessage/targets" in text
    assert "/v1/spark/drafts/imessage/outbox?principal_id=ken&limit=25" in text
    assert "/v1/approvals/pending" in text
    assert "ready was not true" in text
    assert "parent_minor_context_approved" in text
    assert "no sent approved item with one attempt" in text
    assert "pending Spark approval" in text
    assert "no live send attempted" in text
    assert "draft_text" in text
    assert "chat_guid" in text
    assert "phone_number" in text
    assert "/send" not in text
    assert "--data-binary" not in text
    assert "request_json" not in text
    assert "post_json" not in text
