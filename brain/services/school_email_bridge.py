from __future__ import annotations

import os
from dataclasses import replace
from hashlib import sha256

import asyncpg

from brain.services.family_school_client import FamilySchoolClient
from brain.services.gmail_client import GmailMessage
from brain.services.school_email_parser import (
    SchoolActionCandidate,
    SchoolEmailExtraction,
    SchoolEventCandidate,
)
from brain.services.school_email_repository import PersistedCandidate
from brain.services.school_email_rules import SchoolEmailScanRule

DEFAULT_IMPORT_CONFIDENCE = 0.78


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _scoped_external_id(
    *,
    base_external_id: str,
    rule: SchoolEmailScanRule,
    kind: str,
) -> str:
    if not rule.child_member_id:
        return base_external_id
    basis = f"{base_external_id}|{rule.child_member_id}"
    digest = sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"alpha:gmail:school:{kind}:{digest}"


def apply_rule_context(
    extraction: SchoolEmailExtraction,
    rule: SchoolEmailScanRule,
) -> tuple[list[SchoolEventCandidate], list[SchoolActionCandidate]]:
    return (
        [_apply_event_rule(candidate, rule) for candidate in extraction.events],
        [_apply_action_rule(candidate, rule) for candidate in extraction.actions],
    )


def _apply_event_rule(
    candidate: SchoolEventCandidate,
    rule: SchoolEmailScanRule,
) -> SchoolEventCandidate:
    return replace(
        candidate,
        child_member_id=rule.child_member_id,
        child_name=rule.child_name,
        family_external_id=_scoped_external_id(
            base_external_id=candidate.family_external_id,
            rule=rule,
            kind="event",
        ),
    )


def _apply_action_rule(
    candidate: SchoolActionCandidate,
    rule: SchoolEmailScanRule,
) -> SchoolActionCandidate:
    return replace(
        candidate,
        child_member_id=rule.child_member_id,
        child_name=rule.child_name,
        family_external_id=_scoped_external_id(
            base_external_id=candidate.family_external_id,
            rule=rule,
            kind="action",
        ),
    )


def _metadata(
    *,
    persisted_id: str,
    message: GmailMessage,
    candidate: SchoolEventCandidate | SchoolActionCandidate,
    rule: SchoolEmailScanRule,
) -> dict:
    return {
        "alpha_candidate_id": persisted_id,
        "gmail_message_id": message.gmail_message_id,
        "school_name": "Mount Pisgah",
        "confidence": candidate.confidence,
        "child_name": candidate.child_name,
        "sender_rule_id": rule.id,
        "sender_rule_type": rule.rule_type,
    }


def _time_value(value) -> str | None:
    return value.isoformat(timespec="minutes") if value else None


def _should_import(persisted: PersistedCandidate, confidence: float) -> bool:
    if persisted.family_id or persisted.status in {"imported", "ignored"}:
        return False
    return confidence >= _float_env(
        "ALPHA_SCHOOL_EMAIL_AUTO_IMPORT_MIN_CONFIDENCE",
        DEFAULT_IMPORT_CONFIDENCE,
    )


async def import_event(
    conn: asyncpg.Connection,
    family_client: FamilySchoolClient,
    *,
    persisted: PersistedCandidate,
    message: GmailMessage,
    candidate: SchoolEventCandidate,
    rule: SchoolEmailScanRule,
) -> bool:
    if not _should_import(persisted, candidate.confidence):
        return False
    imported = await family_client.import_event(
        {
            "title": candidate.title,
            "event_date": candidate.event_date.isoformat(),
            "event_time": _time_value(candidate.event_time),
            "notes": candidate.notes,
            "location": candidate.location,
            "external_id": candidate.family_external_id,
            "child_member_id": candidate.child_member_id,
            "source_metadata": _metadata(
                persisted_id=persisted.id,
                message=message,
                candidate=candidate,
                rule=rule,
            ),
        }
    )
    await conn.execute(
        """
        UPDATE public.alpha_school_event_candidates
        SET status = 'imported',
            family_event_id = $2::uuid,
            reviewed_by = 'alpha-school-email',
            reviewed_at = now(),
            updated_at = now()
        WHERE id = $1::uuid
        """,
        persisted.id,
        imported.get("id"),
    )
    return True


async def import_action(
    conn: asyncpg.Connection,
    family_client: FamilySchoolClient,
    *,
    persisted: PersistedCandidate,
    message: GmailMessage,
    candidate: SchoolActionCandidate,
    rule: SchoolEmailScanRule,
) -> bool:
    if not _should_import(persisted, candidate.confidence):
        return False
    imported = await family_client.import_action(
        {
            "title": candidate.title,
            "action_date": candidate.action_date.isoformat(),
            "action_time": _time_value(candidate.action_time),
            "notes": candidate.notes,
            "external_id": candidate.family_external_id,
            "child_member_id": candidate.child_member_id,
            "source_metadata": _metadata(
                persisted_id=persisted.id,
                message=message,
                candidate=candidate,
                rule=rule,
            ),
        }
    )
    await conn.execute(
        """
        UPDATE public.alpha_school_action_candidates
        SET status = 'imported',
            family_action_id = $2::uuid,
            reviewed_by = 'alpha-school-email',
            reviewed_at = now(),
            updated_at = now()
        WHERE id = $1::uuid
        """,
        persisted.id,
        imported.get("id"),
    )
    return True
