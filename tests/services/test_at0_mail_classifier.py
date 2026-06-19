from brain.services.at0_mail_classifier import classify_at0_mail, should_create_draft


def test_classify_support_mailbox_as_support() -> None:
    result = classify_at0_mail(
        mailbox="support@at-0.com",
        sender_email="customer@example.com",
        subject="Login issue",
        body_preview="I cannot access my account.",
    )

    assert result.classification == "support"
    assert result.priority == "medium"
    assert should_create_draft(result.classification)


def test_classify_waitlist_message_as_lead() -> None:
    result = classify_at0_mail(
        mailbox="hello@at-0.com",
        sender_email="cto@example.com",
        subject="Enterprise demo",
        body_preview="We are interested in private AI for our security team.",
    )

    assert result.classification == "lead"
    assert result.priority == "high"


def test_classify_newsletter_as_noise_without_draft() -> None:
    result = classify_at0_mail(
        mailbox="hello@at-0.com",
        sender_email="noreply@example.com",
        subject="Newsletter",
        body_preview="Unsubscribe here.",
    )

    assert result.classification == "noise"
    assert result.priority == "low"
    assert not should_create_draft(result.classification)
