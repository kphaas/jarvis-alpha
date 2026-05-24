from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import asyncpg

from brain.db.pool import get_pool
from brain.services.gmail_client import GmailClient, GmailMessage
from brain.services.school_email_parser import (
    SchoolEventCandidate,
    extract_school_events,
)

DEFAULT_SCHOOL_QUERY = '("Mount Pisgah" OR "MPCS" OR "Pisgah") newer_than:21d'


class MessageClient(Protocol):
    async def list_message_ids(
        self, query: str, max_results: int = 25
    ) -> list[str]: ...

    async def get_message(self, message_id: str) -> GmailMessage: ...


@dataclass(frozen=True)
class SchoolEmailScanResult:
    messages_seen: int
    messages_new: int
    candidates_created: int
    candidates_existing: int


async def _message_exists(conn: asyncpg.Connection, gmail_message_id: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1
            FROM public.alpha_school_email_messages
            WHERE gmail_message_id = $1
            """,
            gmail_message_id,
        )
    )


async def _record_message(
    conn: asyncpg.Connection,
    message: GmailMessage,
) -> str:
    return str(
        await conn.fetchval(
            """
            INSERT INTO public.alpha_school_email_messages (
                gmail_message_id, gmail_thread_id, history_id, sender, subject,
                received_at, snippet, body_sha256, classification
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'school')
            ON CONFLICT (gmail_message_id) DO UPDATE
            SET gmail_thread_id = EXCLUDED.gmail_thread_id,
                history_id = EXCLUDED.history_id,
                sender = EXCLUDED.sender,
                subject = EXCLUDED.subject,
                received_at = EXCLUDED.received_at,
                snippet = EXCLUDED.snippet,
                body_sha256 = EXCLUDED.body_sha256,
                processed_at = now(),
                updated_at = now()
            RETURNING id
            """,
            message.gmail_message_id,
            message.thread_id,
            message.history_id,
            message.sender,
            message.subject,
            message.received_at,
            message.snippet,
            message.body_sha256,
        )
    )


async def _record_candidate(
    conn: asyncpg.Connection,
    message_id: str,
    gmail_message_id: str,
    candidate: SchoolEventCandidate,
) -> bool:
    status = "needs_review"
    auto_threshold = os.environ.get("ALPHA_SCHOOL_EMAIL_AUTO_APPROVE_MIN_CONFIDENCE")
    if auto_threshold:
        try:
            if candidate.confidence >= float(auto_threshold):
                status = "approved"
        except ValueError:
            status = "needs_review"
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_school_event_candidates (
            email_message_id, gmail_message_id, title, event_date, event_time,
            end_time, location, notes, confidence, family_external_id, status
        )
        VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (family_external_id) DO NOTHING
        RETURNING id
        """,
        message_id,
        gmail_message_id,
        candidate.title,
        candidate.event_date,
        candidate.event_time,
        candidate.end_time,
        candidate.location,
        candidate.notes,
        candidate.confidence,
        candidate.family_external_id,
        status,
    )
    return row is not None


async def scan_school_email(
    *,
    client: MessageClient | None = None,
    query: str | None = None,
    max_results: int = 25,
    anchor: date | None = None,
) -> SchoolEmailScanResult:
    gmail = client or GmailClient()
    school_query = query or os.environ.get(
        "ALPHA_SCHOOL_EMAIL_QUERY", DEFAULT_SCHOOL_QUERY
    )
    message_ids = await gmail.list_message_ids(school_query, max_results=max_results)

    messages_new = 0
    candidates_created = 0
    candidates_existing = 0
    pool = get_pool()
    async with pool.acquire() as conn:
        for gmail_message_id in message_ids:
            if await _message_exists(conn, gmail_message_id):
                continue
            message = await gmail.get_message(gmail_message_id)
            messages_new += 1
            message_row_id = await _record_message(conn, message)
            candidates = await extract_school_events(message, anchor=anchor)
            for candidate in candidates:
                created = await _record_candidate(
                    conn, message_row_id, message.gmail_message_id, candidate
                )
                if created:
                    candidates_created += 1
                else:
                    candidates_existing += 1

    return SchoolEmailScanResult(
        messages_seen=len(message_ids),
        messages_new=messages_new,
        candidates_created=candidates_created,
        candidates_existing=candidates_existing,
    )
