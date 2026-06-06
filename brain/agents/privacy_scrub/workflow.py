"""Manual workflow for approved privacy actions.

P3-D through P3-G record local operator state only. The repository updates
approved action records, stores operator notes/evidence as encrypted payloads,
and appends immutable action events. It does not contact targets or automate
filings.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

import asyncpg

from brain.agents.privacy_scrub.crypto import EncryptedPayload, PrivacyCrypto
from brain.agents.privacy_scrub.state import (
    StoredApprovedPrivacyAction,
    StoredCaseDraft,
    StoredPrivacyActionEvent,
    append_action_event,
    get_case_draft,
    list_privacy_action_events_for_case,
    list_privacy_actions_for_case,
    mark_case_draft_completed_if_terminal,
    update_privacy_action_manual_disposition,
    update_privacy_action_verification,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("privacy_scrub.workflow")


class PrivacyActionWorkflowError(ValueError):
    """Base error for invalid approved-action workflow updates."""


class PrivacyActionWorkflowNotFound(PrivacyActionWorkflowError):
    """The requested action or case is not visible to the current RLS actor."""


class PrivacyActionWorkflowTransitionError(PrivacyActionWorkflowError):
    """The requested workflow transition is not valid for the action."""


@dataclass(frozen=True, slots=True)
class PrivacyActionWorkflowResult:
    action: StoredApprovedPrivacyAction
    event_type: str


@dataclass(frozen=True, slots=True)
class PrivacyCaseTimeline:
    case_draft: StoredCaseDraft
    events: tuple[StoredPrivacyActionEvent, ...]


@dataclass(frozen=True, slots=True)
class PrivacyCaseReport:
    case_draft: StoredCaseDraft
    actions: tuple[StoredApprovedPrivacyAction, ...]
    events: tuple[StoredPrivacyActionEvent, ...]
    generated_at: datetime


class PrivacyActionWorkflowRepository:
    """Record local approved-action handling through an RLS-bound connection."""

    def __init__(self, conn: asyncpg.Connection, crypto: PrivacyCrypto) -> None:
        self._conn = conn
        self._crypto = crypto

    async def record_manual_disposition(
        self,
        *,
        action_id: UUID,
        actor: str,
        disposition: str,
        operator_note: str | None = None,
        evidence_reference: str | None = None,
        verification_due_at: datetime | None = None,
    ) -> PrivacyActionWorkflowResult:
        actor = _clean_required(actor, "actor")
        disposition = _clean_required(disposition, "disposition")
        if disposition not in _MANUAL_DISPOSITIONS:
            raise PrivacyActionWorkflowTransitionError(
                "privacy action disposition invalid"
            )
        if disposition == "deferred" and verification_due_at is None:
            raise PrivacyActionWorkflowTransitionError(
                "privacy action deferral requires a due date"
            )

        note_payload = _encrypted_optional_payload(
            self._crypto,
            {
                "workflow_version": "p3dg-v1",
                "kind": "manual_disposition_note",
                "action_id": str(action_id),
                "disposition": disposition,
                "operator_note": _clean_optional(operator_note),
            },
            required_key="operator_note",
        )
        evidence_payload = _encrypted_optional_payload(
            self._crypto,
            {
                "workflow_version": "p3dg-v1",
                "kind": "manual_disposition_evidence",
                "action_id": str(action_id),
                "disposition": disposition,
                "evidence_reference": _clean_optional(evidence_reference),
            },
            required_key="evidence_reference",
        )
        event_payload = self._crypto.encrypt_json_payload(
            {
                "workflow_version": "p3dg-v1",
                "kind": "manual_disposition",
                "action_id": str(action_id),
                "disposition": disposition,
                "operator_note_present": note_payload is not None,
                "evidence_reference_present": evidence_payload is not None,
                "verification_due_at": _datetime_iso(verification_due_at),
            }
        )

        event_type = _MANUAL_EVENT_TYPES[disposition]
        async with self._conn.transaction():
            action = await update_privacy_action_manual_disposition(
                self._conn,
                action_id=action_id,
                disposition=disposition,
                actor=actor,
                manual_note_ciphertext=_ciphertext(note_payload),
                manual_note_hash=_payload_hash(note_payload),
                evidence_payload_ciphertext=_ciphertext(evidence_payload),
                evidence_payload_hash=_payload_hash(evidence_payload),
                workflow_payload_key_version=self._crypto.payload_key_version,
                verification_due_at=verification_due_at,
            )
            if action is None:
                raise PrivacyActionWorkflowNotFound(
                    "privacy action is not approved or visible"
                )
            await append_action_event(
                self._conn,
                action_id=action_id,
                event_type=event_type,
                actor=actor,
                event_payload_ciphertext=event_payload.ciphertext,
                event_payload_hash=event_payload.payload_hash,
            )
            completed_case = await mark_case_draft_completed_if_terminal(
                self._conn,
                case_draft_id=action.case_draft_id,
            )
            if completed_case is not None:
                action = replace(action, case_status=completed_case.status)

        logger.info(
            "privacy_action_manual_disposition action_id=%s disposition=%s event=%s",
            action_id,
            disposition,
            event_type,
        )
        return PrivacyActionWorkflowResult(action=action, event_type=event_type)

    async def record_verification(
        self,
        *,
        action_id: UUID,
        actor: str,
        outcome: str,
        operator_note: str | None = None,
        evidence_reference: str | None = None,
        verification_due_at: datetime | None = None,
    ) -> PrivacyActionWorkflowResult:
        actor = _clean_required(actor, "actor")
        outcome = _clean_required(outcome, "outcome")
        if outcome not in _VERIFICATION_OUTCOMES:
            raise PrivacyActionWorkflowTransitionError(
                "privacy action verification outcome invalid"
            )
        if outcome == "needs_followup" and verification_due_at is None:
            raise PrivacyActionWorkflowTransitionError(
                "privacy action follow-up requires a due date"
            )

        evidence_payload = _encrypted_optional_payload(
            self._crypto,
            {
                "workflow_version": "p3dg-v1",
                "kind": "verification_evidence",
                "action_id": str(action_id),
                "outcome": outcome,
                "operator_note": _clean_optional(operator_note),
                "evidence_reference": _clean_optional(evidence_reference),
            },
            required_key="evidence_reference",
        )
        event_payload = self._crypto.encrypt_json_payload(
            {
                "workflow_version": "p3dg-v1",
                "kind": "verification",
                "action_id": str(action_id),
                "outcome": outcome,
                "operator_note_present": bool(_clean_optional(operator_note)),
                "evidence_reference_present": evidence_payload is not None,
                "verification_due_at": _datetime_iso(verification_due_at),
            }
        )

        event_type = _VERIFICATION_EVENT_TYPES[outcome]
        async with self._conn.transaction():
            action = await update_privacy_action_verification(
                self._conn,
                action_id=action_id,
                outcome=outcome,
                actor=actor,
                evidence_payload_ciphertext=_ciphertext(evidence_payload),
                evidence_payload_hash=_payload_hash(evidence_payload),
                workflow_payload_key_version=self._crypto.payload_key_version,
                verification_due_at=verification_due_at,
            )
            if action is None:
                raise PrivacyActionWorkflowNotFound(
                    "privacy action is not ready for verification"
                )
            await append_action_event(
                self._conn,
                action_id=action_id,
                event_type=event_type,
                actor=actor,
                event_payload_ciphertext=event_payload.ciphertext,
                event_payload_hash=event_payload.payload_hash,
            )
            completed_case = await mark_case_draft_completed_if_terminal(
                self._conn,
                case_draft_id=action.case_draft_id,
            )
            if completed_case is not None:
                action = replace(action, case_status=completed_case.status)

        logger.info(
            "privacy_action_verification action_id=%s outcome=%s event=%s",
            action_id,
            outcome,
            event_type,
        )
        return PrivacyActionWorkflowResult(action=action, event_type=event_type)


class PrivacyCaseWorkflowReader:
    """Read local case workflow metadata without decrypting payloads."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def get_timeline(self, case_id: UUID) -> PrivacyCaseTimeline:
        case_draft = await get_case_draft(self._conn, case_id)
        if case_draft is None:
            raise PrivacyActionWorkflowNotFound("privacy case not found")
        events = tuple(
            await list_privacy_action_events_for_case(
                self._conn,
                case_draft_id=case_id,
            )
        )
        return PrivacyCaseTimeline(case_draft=case_draft, events=events)

    async def get_report(self, case_id: UUID) -> PrivacyCaseReport:
        case_draft = await get_case_draft(self._conn, case_id)
        if case_draft is None:
            raise PrivacyActionWorkflowNotFound("privacy case not found")
        actions = tuple(
            await list_privacy_actions_for_case(
                self._conn,
                case_draft_id=case_id,
            )
        )
        events = tuple(
            await list_privacy_action_events_for_case(
                self._conn,
                case_draft_id=case_id,
            )
        )
        return PrivacyCaseReport(
            case_draft=case_draft,
            actions=actions,
            events=events,
            generated_at=datetime.now(UTC),
        )


def _encrypted_optional_payload(
    crypto: PrivacyCrypto,
    payload: dict[str, object],
    *,
    required_key: str,
) -> EncryptedPayload | None:
    value = payload.get(required_key)
    if not isinstance(value, str) or not value:
        return None
    return crypto.encrypt_json_payload(payload)


def _ciphertext(payload: EncryptedPayload | None) -> bytes | None:
    return payload.ciphertext if payload else None


def _payload_hash(payload: EncryptedPayload | None) -> str | None:
    return payload.payload_hash if payload else None


def _clean_required(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise PrivacyActionWorkflowTransitionError(f"{field_name} is required")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _datetime_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


_MANUAL_DISPOSITIONS = {"handled", "deferred", "blocked"}
_VERIFICATION_OUTCOMES = {"confirmed", "needs_followup", "failed"}
_MANUAL_EVENT_TYPES = {
    "handled": "sent",
    "deferred": "verification_scheduled",
    "blocked": "failed",
}
_VERIFICATION_EVENT_TYPES = {
    "confirmed": "confirmed",
    "needs_followup": "verification_scheduled",
    "failed": "failed",
}
