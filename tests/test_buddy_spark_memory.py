from __future__ import annotations

from brain.agents.buddy_agent import spark_memory_summary_body


def test_spark_memory_summary_body_reports_available_context() -> None:
    body = spark_memory_summary_body(
        {
            "principal_id": "ken",
            "status": "ok",
            "line_count": 12,
            "feedback_count": 3,
        }
    )

    assert "Spark persona grounding is available for ken." in body
    assert "Runtime context lines: 12." in body
    assert "Draft-edit feedback waiting for review: 3." in body


def test_spark_memory_summary_body_reports_unavailable_context() -> None:
    body = spark_memory_summary_body(
        {
            "principal_id": "ken",
            "status": "unavailable",
            "error_class": "SparkVoiceIngestError",
        }
    )

    assert "Spark persona grounding is unavailable for ken." in body
    assert "Error class: SparkVoiceIngestError." in body
