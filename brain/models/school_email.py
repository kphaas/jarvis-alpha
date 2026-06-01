from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SchoolEmailScanResponse(BaseModel):
    scan_run_id: str | None = None
    messages_seen: int
    messages_new: int
    candidates_created: int
    candidates_existing: int
    event_candidates_created: int = 0
    event_candidates_existing: int = 0
    action_candidates_created: int = 0
    action_candidates_existing: int = 0
    events_imported: int = 0
    actions_imported: int = 0
    import_errors: int = 0
    rules_loaded: int = 0
    queries_run: int = 0


class SchoolEmailScanRunOut(BaseModel):
    id: UUID
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    lookback_days: int
    max_results: int
    import_to_family: bool
    manual_query: bool
    rules_loaded: int
    queries_run: int
    messages_seen: int
    messages_new: int
    event_candidates_created: int
    action_candidates_created: int
    events_imported: int
    actions_imported: int
    import_errors: int
    error_type: str | None = None
    error_message: str | None = None


class GmailOAuthHealthOut(BaseModel):
    id: UUID | None = None
    status: Literal["ok", "failed", "unknown"]
    checked_at: datetime | None = None
    last_successful_refresh_at: datetime | None = None
    token_expires_in: int | None = None
    scope: str | None = None
    error_type: str | None = None
    error_subtype: str | None = None
    error_message: str | None = None
    oauth_mode: str
    refresh_token_issued_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    refresh_token_days_remaining: int | None = None
    reconnect_recommended: bool


class SchoolEventCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gmail_message_id: str
    source: str
    school_name: str
    child_member_id: UUID | None = None
    child_name: str | None = None
    title: str
    event_date: date
    event_time: time | None
    end_time: time | None
    location: str | None
    notes: str | None
    confidence: float
    status: str
    family_external_id: str
    family_event_id: UUID | None
    sender: str | None
    subject: str | None
    received_at: datetime | None
    created_at: datetime
    family_import: dict


class SchoolEventCandidateList(BaseModel):
    candidates: list[SchoolEventCandidateOut]


class SchoolActionCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gmail_message_id: str
    source: str
    school_name: str
    child_member_id: UUID | None = None
    child_name: str | None = None
    title: str
    action_date: date
    action_time: time | None
    notes: str | None
    confidence: float
    status: str
    family_external_id: str
    family_action_id: UUID | None
    sender: str | None
    subject: str | None
    received_at: datetime | None
    created_at: datetime
    family_import: dict


class SchoolActionCandidateList(BaseModel):
    candidates: list[SchoolActionCandidateOut]


class CandidateStatusUpdate(BaseModel):
    status: Literal["approved", "ignored", "needs_review", "imported"]
    family_event_id: UUID | None = None
    family_action_id: UUID | None = None
