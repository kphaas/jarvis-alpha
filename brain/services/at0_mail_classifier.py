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


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)
