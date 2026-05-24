from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SchoolEmailScanResponse(BaseModel):
    messages_seen: int
    messages_new: int
    candidates_created: int
    candidates_existing: int


class SchoolEventCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gmail_message_id: str
    source: str
    school_name: str
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


class CandidateStatusUpdate(BaseModel):
    status: Literal["approved", "ignored", "needs_review", "imported"]
    family_event_id: UUID | None = None
