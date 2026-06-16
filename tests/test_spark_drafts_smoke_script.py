from pathlib import Path


SCRIPT = Path("scripts/smoke_spark_drafts.sh")


def test_spark_drafts_smoke_script_avoids_secret_tracing() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "set -x" not in text
    assert "bash -x" not in text
    assert "BLUEBUBBLES_PASSWORD" not in text
    assert "echo ${TOKEN}" not in text
    assert 'echo "$TOKEN"' not in text
    assert "curl -v" not in text


def test_spark_drafts_smoke_script_checks_draft_only_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert ".venv/bin/python" in text
    assert "SPARK_SMOKE_PYTHON" in text
    assert "spark.draft,imessage.read" in text
    assert "/v1/spark/drafts/imessage/targets" in text
    assert "/v1/spark/drafts/imessage/target-preview" in text
    assert "/v1/spark/drafts/imessage" in text
    assert "/v1/spark/drafts/imessage/approval-request" in text
    assert "SPARK_DRAFT_SMOKE_QUEUE_APPROVAL" in text
    assert "context_preview" in text
    assert "more than 8 messages returned" in text
    assert "can_send" in text
    assert "requires_human_approval" in text
    assert "durable_storage_allowed" in text
    assert "chat_guid_hash" not in text
    assert '"chat_guid"' in text
    assert '"chatGuid"' in text
    assert "phone_number" in text
