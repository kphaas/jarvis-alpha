from __future__ import annotations

from dataclasses import dataclass

from brain.services.at0_mail_classifier import MailClassification
from brain.services.at0_mail_graph_client import At0MailMessage


AT0_SPARK_ID = "at0-spark"
AT0_SPARK_DRAFT_ENGINE = "at0_spark_deterministic_v1"


@dataclass(frozen=True, slots=True)
class At0SparkProfile:
    spark_id: str
    display_name: str
    channel: str
    voice: tuple[str, ...]
    reply_boundaries: tuple[str, ...]
    can_send: bool
    requires_human_approval: bool
    draft_engine: str

    def to_payload(self) -> dict[str, object]:
        return {
            "spark_id": self.spark_id,
            "display_name": self.display_name,
            "channel": self.channel,
            "voice": list(self.voice),
            "reply_boundaries": list(self.reply_boundaries),
            "can_send": self.can_send,
            "requires_human_approval": self.requires_human_approval,
            "draft_engine": self.draft_engine,
        }


@dataclass(frozen=True, slots=True)
class At0SparkDraft:
    proposed_body: str
    draft_engine: str
    can_send: bool
    requires_human_approval: bool
    warnings: tuple[str, ...]


def at0_spark_profile() -> At0SparkProfile:
    return At0SparkProfile(
        spark_id=AT0_SPARK_ID,
        display_name="AT-0 Spark",
        channel="email",
        voice=(
            "plainspoken",
            "privacy-first",
            "low-hype",
            "specific about next review step",
        ),
        reply_boundaries=(
            "drafts only; never send",
            "no mailbox mutation",
            "no commitments without human review",
            "do not mention internal classifications",
        ),
        can_send=False,
        requires_human_approval=True,
        draft_engine=AT0_SPARK_DRAFT_ENGINE,
    )


def create_at0_spark_reply_draft(
    *,
    message: At0MailMessage,
    classification: MailClassification,
) -> At0SparkDraft:
    profile = at0_spark_profile()
    greeting = _greeting(message.sender_name)
    body = _classification_body(classification.classification)
    topic = _topic(message.subject)

    proposed_body = "\n\n".join(
        [
            greeting,
            body,
            f"Reference: {topic}",
            "Best,\nAT-0",
        ]
    )
    return At0SparkDraft(
        proposed_body=proposed_body,
        draft_engine=profile.draft_engine,
        can_send=profile.can_send,
        requires_human_approval=profile.requires_human_approval,
        warnings=("draft_only_no_send", "human_review_required"),
    )


def _greeting(sender_name: str | None) -> str:
    if not sender_name:
        return "Hi,"
    clean = " ".join(sender_name.strip().split())
    if not clean:
        return "Hi,"
    first = clean.split(" ", 1)[0].strip(",")
    return f"Hi {first},"


def _topic(subject: str | None) -> str:
    clean = " ".join((subject or "your note").strip().split())
    return clean or "your note"


def _classification_body(classification: str) -> str:
    if classification == "support":
        return (
            "Thanks for reaching out to AT-0 support. I have your note and will "
            "route it for human review before we take any action."
        )
    if classification == "press":
        return (
            "Thanks for reaching out about AT-0. Ken reviews press requests "
            "directly, and I will get this in front of him with the right context."
        )
    if classification == "partner":
        return (
            "Thanks for the partnership note. AT-0 is focused on private AI "
            "infrastructure, and I will review where this could fit before we "
            "respond with next steps."
        )
    if classification == "investor":
        return (
            "Thanks for reaching out. Ken reviews investor conversations "
            "personally, and I will flag this for review before any follow-up."
        )
    return (
        "Thanks for your interest in AT-0. We are building private AI "
        "infrastructure with human approval, domain isolation, and no data "
        "resale. I will route this for review and follow up with next steps."
    )
