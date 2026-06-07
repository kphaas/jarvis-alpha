from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class At0MailScanResponse(BaseModel):
    scan_run_id: str | None
    mailboxes_scanned: int
    messages_seen: int
    messages_new: int
    draft_proposals_created: int


class At0MailScanRunOut(BaseModel):
    id: UUID
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    mailbox_count: int
    max_results: int
    messages_seen: int
    messages_new: int
    draft_proposals_created: int
    error_type: str | None = None
    error_message: str | None = None


class At0MailCountRow(BaseModel):
    mailbox: str | None = None
    classification: str | None = None
    status: str
    priority: str | None = None
    count: int


class At0MailDraftCountRow(BaseModel):
    status: str
    count: int


class At0MailDashboardOut(BaseModel):
    message_counts: list[At0MailCountRow]
    draft_counts: list[At0MailDraftCountRow]
    latest_scan: At0MailScanRunOut | None = None


class At0MailMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mailbox: str
    graph_message_id: str
    internet_message_id: str | None
    conversation_id: str | None
    sender_name: str | None
    sender_email: str | None
    subject: str | None
    received_at: datetime | None
    body_preview: str | None
    web_link: str | None
    classification: str
    priority: str
    status: str
    classification_reason: str
    created_at: datetime


class At0MailMessageList(BaseModel):
    messages: list[At0MailMessageOut]


class At0MailDraftProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mail_message_id: UUID
    mailbox: str
    recipient_email: str | None
    reply_subject: str
    proposed_body: str
    status: str
    reviewer_notes: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    sender_name: str | None
    sender_email: str | None
    original_subject: str | None
    received_at: datetime | None
    classification: str
    priority: str


class At0MailDraftProposalList(BaseModel):
    drafts: list[At0MailDraftProposalOut]


class At0MailDraftStatusUpdate(BaseModel):
    status: Literal["needs_review", "approved", "rejected"]
    reviewer_notes: str | None = None
