from brain.services.spark_corpus_ingest import (
    SparkCorpusApproval,
    plan_approved_corpus_ingest,
)


def test_approved_one_to_one_plan_allows_principal_sent_messages_only() -> None:
    plan = plan_approved_corpus_ingest(
        SparkCorpusApproval(
            principal_id="ken",
            source="imessage",
            approval_id="spark-approval-001",
            thread_kind="one_to_one",
            include_inbound_runtime_context=True,
        )
    )

    assert plan.allowed is True
    assert plan.body_access_required is True
    assert plan.durable_voice_source == "principal_sent_messages_only"
    assert plan.runtime_context_allowed is True
    assert plan.allowed_operations == (
        "read_approved_source",
        "extract_principal_sent_messages",
        "load_inbound_runtime_context",
    )
    assert "store_inbound_message_text" in plan.blocked_operations
    assert "do_not_log_message_bodies" in plan.redaction_rules


def test_legal_marked_thread_is_denied_before_body_access() -> None:
    plan = plan_approved_corpus_ingest(
        SparkCorpusApproval(
            principal_id="ken",
            source="imessage",
            approval_id="spark-approval-002",
            thread_kind="one_to_one",
            legal_marked=True,
        )
    )

    assert plan.allowed is False
    assert plan.reason == "legal_marked_content_requires_manual_review"
    assert plan.body_access_required is False
    assert plan.durable_voice_source == "none"


def test_relationship_marked_thread_requires_specific_approval() -> None:
    denied = plan_approved_corpus_ingest(
        SparkCorpusApproval(
            principal_id="ken",
            source="imessage",
            approval_id="spark-approval-003",
            thread_kind="one_to_one",
            relationship_marked=True,
        )
    )
    allowed = plan_approved_corpus_ingest(
        SparkCorpusApproval(
            principal_id="ken",
            source="imessage",
            approval_id="spark-approval-003",
            thread_kind="one_to_one",
            relationship_marked=True,
            relationship_approved=True,
        )
    )

    assert denied.allowed is False
    assert denied.reason == "relationship_marked_content_requires_specific_approval"
    assert allowed.allowed is True


def test_group_threads_are_denied_for_phase_two() -> None:
    plan = plan_approved_corpus_ingest(
        SparkCorpusApproval(
            principal_id="ken",
            source="imessage",
            approval_id="spark-approval-004",
            thread_kind="group",
        )
    )

    assert plan.allowed is False
    assert plan.reason == "phase_two_requires_one_to_one_thread"
    assert plan.allowed_operations == ()
