from __future__ import annotations

from datetime import UTC, datetime

from brain.services.at0_mail_classifier import MailClassification
from brain.services.at0_mail_graph_client import At0MailMessage
from brain.services.at0_spark import (
    AT0_SPARK_DRAFT_ENGINE,
    at0_spark_profile,
    create_at0_spark_reply_draft,
)


def _message(
    *,
    sender_name: str | None = "Casey Morgan",
    subject: str | None = "Founding access",
) -> At0MailMessage:
    return At0MailMessage(
        graph_message_id="graph-1",
        mailbox="hello@at-0.com",
        internet_message_id="<msg@example.com>",
        conversation_id="conv-1",
        sender_name=sender_name,
        sender_email="casey@example.com",
        subject=subject,
        received_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        body_preview="We are interested in private AI infrastructure.",
        web_link=None,
    )


def test_at0_spark_profile_is_draft_only() -> None:
    profile = at0_spark_profile()

    assert profile.spark_id == "at0-spark"
    assert profile.display_name == "AT-0 Spark"
    assert profile.can_send is False
    assert profile.requires_human_approval is True
    assert profile.draft_engine == AT0_SPARK_DRAFT_ENGINE
    assert "drafts only; never send" in profile.reply_boundaries


def test_at0_spark_drafts_lead_reply_in_at0_voice() -> None:
    draft = create_at0_spark_reply_draft(
        message=_message(),
        classification=MailClassification(
            classification="lead",
            priority="high",
            reason="signup or sales interest detected",
        ),
    )

    assert draft.can_send is False
    assert draft.requires_human_approval is True
    assert draft.draft_engine == AT0_SPARK_DRAFT_ENGINE
    assert "Hi Casey," in draft.proposed_body
    assert "private AI infrastructure" in draft.proposed_body
    assert "human approval" in draft.proposed_body
    assert "Reference: Founding access" in draft.proposed_body
    assert "AT-0" in draft.proposed_body


def test_at0_spark_support_reply_does_not_commit_to_action() -> None:
    draft = create_at0_spark_reply_draft(
        message=_message(sender_name=None, subject="Login issue"),
        classification=MailClassification(
            classification="support",
            priority="medium",
            reason="support intent detected",
        ),
    )

    assert draft.proposed_body.startswith("Hi,")
    assert "human review before we take any action" in draft.proposed_body
    assert "draft_only_no_send" in draft.warnings
    assert "human_review_required" in draft.warnings
