from __future__ import annotations

from dataclasses import dataclass

from brain.db.pool import get_pool
from brain.services.at0_mail_classifier import (
    classify_at0_mail,
    should_create_draft,
)
from brain.services.at0_mail_graph_client import (
    At0MailGraphClient,
    configured_mailboxes,
)
from brain.services.at0_mail_repository import (
    fail_scan_run,
    finish_scan_run,
    record_draft_proposal,
    record_message,
    start_scan_run,
)
from brain.services.at0_spark import create_at0_spark_reply_draft


@dataclass(frozen=True)
class At0MailScanResult:
    scan_run_id: str | None
    mailboxes_scanned: int
    messages_seen: int
    messages_new: int
    draft_proposals_created: int


async def scan_at0_mail(
    *,
    client: At0MailGraphClient | None = None,
    mailboxes: tuple[str, ...] | None = None,
    max_results: int = 25,
    trigger: str = "manual",
) -> At0MailScanResult:
    graph = client or At0MailGraphClient()
    mailbox_list = mailboxes or configured_mailboxes()
    bounded_max = min(max(max_results, 1), 50)
    pool = get_pool()

    async with pool.acquire() as conn:
        scan_run_id = await start_scan_run(
            conn,
            trigger=trigger,
            mailbox_count=len(mailbox_list),
            max_results=bounded_max,
        )

    try:
        result = await _scan_mailboxes(
            pool=pool,
            graph=graph,
            mailboxes=mailbox_list,
            max_results=bounded_max,
            scan_run_id=scan_run_id,
        )
    except Exception as exc:
        async with pool.acquire() as conn:
            await fail_scan_run(conn, scan_run_id, exc)
        raise

    async with pool.acquire() as conn:
        await finish_scan_run(conn, scan_run_id, result)
    return result


async def _scan_mailboxes(
    *,
    pool,
    graph: At0MailGraphClient,
    mailboxes: tuple[str, ...],
    max_results: int,
    scan_run_id: str,
) -> At0MailScanResult:
    messages_seen = 0
    messages_new = 0
    draft_proposals_created = 0

    async with pool.acquire() as conn:
        for mailbox in mailboxes:
            messages = await graph.list_messages(
                mailbox=mailbox,
                max_results=max_results,
            )
            messages_seen += len(messages)
            for message in messages:
                classification = classify_at0_mail(
                    mailbox=message.mailbox,
                    sender_email=message.sender_email,
                    subject=message.subject,
                    body_preview=message.body_preview,
                )
                wants_draft = should_create_draft(classification.classification)
                persisted = await record_message(
                    conn,
                    message=message,
                    classification=classification,
                    status="drafted" if wants_draft else "triaged",
                )
                messages_new += int(persisted.created)
                if not persisted.created or not wants_draft:
                    continue
                draft = create_at0_spark_reply_draft(
                    message=message,
                    classification=classification,
                )
                await record_draft_proposal(
                    conn,
                    message_id=persisted.id,
                    mailbox=message.mailbox,
                    recipient_email=message.sender_email,
                    reply_subject=_reply_subject(message.subject),
                    proposed_body=draft.proposed_body,
                )
                draft_proposals_created += 1

    return At0MailScanResult(
        scan_run_id=scan_run_id,
        mailboxes_scanned=len(mailboxes),
        messages_seen=messages_seen,
        messages_new=messages_new,
        draft_proposals_created=draft_proposals_created,
    )


def _reply_subject(subject: str | None) -> str:
    if not subject:
        return "Re: your note to At-0"
    clean = subject.strip()
    if clean.lower().startswith("re:"):
        return clean
    return f"Re: {clean}"
