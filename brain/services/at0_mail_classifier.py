from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MailClassification:
    classification: str
    priority: str
    reason: str


_NOISE_MARKERS = (
    "unsubscribe",
    "newsletter",
    "no-reply",
    "noreply",
    "do not reply",
    "marketing digest",
)
_SUPPORT_MARKERS = (
    "support",
    "help",
    "issue",
    "bug",
    "problem",
    "can't",
    "cannot",
    "error",
    "login",
)
_LEAD_MARKERS = (
    "sign up",
    "signup",
    "waitlist",
    "demo",
    "pricing",
    "early access",
    "founding",
    "invite",
    "trial",
    "interested",
)
_PRESS_MARKERS = ("press", "media", "interview", "podcast", "journalist", "story")
_PARTNER_MARKERS = ("partner", "partnership", "integration", "reseller", "channel")
_INVESTOR_MARKERS = ("investor", "fund", "venture", "seed", "angel", "capital")
_VENDOR_MARKERS = ("invoice", "vendor", "proposal", "quote", "procurement")
_HIGH_MARKERS = (
    "enterprise",
    "security",
    "compliance",
    "investor",
    "press",
    "urgent",
    "partnership",
)


def classify_at0_mail(
    *,
    mailbox: str,
    sender_email: str | None,
    subject: str | None,
    body_preview: str | None,
) -> MailClassification:
    text = " ".join(
        part
        for part in (
            mailbox,
            sender_email or "",
            subject or "",
            body_preview or "",
        )
        if part
    ).lower()
    support_mailbox = mailbox.lower().startswith("support@")

    if _contains_any(text, _NOISE_MARKERS):
        return MailClassification("noise", "low", "newsletter or automated sender")
    if _contains_any(text, _INVESTOR_MARKERS):
        return MailClassification("investor", "high", "investor language detected")
    if _contains_any(text, _PRESS_MARKERS):
        return MailClassification("press", "high", "press or media language detected")
    if _contains_any(text, _PARTNER_MARKERS):
        return MailClassification("partner", "high", "partnership language detected")
    if support_mailbox or _contains_any(text, _SUPPORT_MARKERS):
        priority = "high" if _contains_any(text, _HIGH_MARKERS) else "medium"
        return MailClassification("support", priority, "support intent detected")
    if _contains_any(text, _LEAD_MARKERS):
        priority = "high" if _contains_any(text, _HIGH_MARKERS) else "medium"
        return MailClassification("lead", priority, "signup or sales interest detected")
    if _contains_any(text, _VENDOR_MARKERS):
        return MailClassification(
            "vendor", "low", "vendor or procurement language detected"
        )
    if mailbox.lower().startswith("hello@"):
        return MailClassification("lead", "medium", "general hello mailbox inquiry")
    return MailClassification("unknown", "low", "no strong business intent matched")


def should_create_draft(classification: str) -> bool:
    return classification in {"lead", "support", "press", "partner", "investor"}


def build_reply_draft(
    *,
    classification: str,
    sender_name: str | None,
    subject: str | None,
) -> str:
    greeting = f"Hi {sender_name.strip()}," if sender_name else "Hi,"
    topic = subject.strip() if subject else "your note"
    if classification == "support":
        body = (
            "Thanks for reaching out to At-0 support. I have your message and will "
            "route it for review before we take action."
        )
    elif classification == "press":
        body = (
            "Thanks for reaching out about At-0. Ken reviews press requests directly, "
            "and I will get this in front of him with the right context."
        )
    elif classification == "partner":
        body = (
            "Thanks for the partnership note. At-0 is focused on private AI infrastructure, "
            "and I will review where this could fit before we respond with next steps."
        )
    elif classification == "investor":
        body = (
            "Thanks for reaching out. Ken reviews investor conversations personally, "
            "and I will flag this for review before any follow-up."
        )
    else:
        body = (
            "Thanks for your interest in At-0. We are building private AI infrastructure "
            "with human approval, domain isolation, and no data resale. I will route this "
            "for review and follow up with next steps."
        )

    return "\n\n".join(
        [
            greeting,
            body,
            f"Context: {topic}",
            "Best,\nAt-0",
        ]
    )


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)
