"""Draft review packets for privacy-scrub P2-E.

This module creates local review packets only. It does not scan targets, send
opt-outs, file court motions, or invoke browser/network automation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

import asyncpg

from brain.agents.privacy_scrub.crypto import (
    EncryptedPayload,
    PrivacyCrypto,
    sha256_digest,
)
from brain.agents.privacy_scrub.policy import ActionType, ApprovalTier, evaluate_tier
from brain.agents.privacy_scrub.state import (
    StoredCaseDraft,
    StoredCaseDraftListItem,
    StoredDraftAction,
    StoredSubject,
    append_action_event,
    get_case_draft_payload,
    get_subject,
    get_target,
    insert_case_draft,
    insert_draft_action,
    list_case_drafts,
    list_draft_actions_for_case,
    list_identity_tuples,
)
from brain.agents.privacy_scrub.subjects import Subject
from brain.agents.privacy_scrub.targets import (
    Jurisdiction,
    OptOutMethod,
    Target,
    TargetCategory,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("privacy_scrub.drafts")


class PrivacyDraftError(ValueError):
    """Base error for invalid draft packet creation."""


class PrivacyDraftSubjectNotFound(PrivacyDraftError):
    """The requested subject is not visible to the current RLS actor."""


class PrivacyDraftTargetNotFound(PrivacyDraftError):
    """A selected target does not exist in the local target cache."""


class PrivacyDraftCaseNotFound(PrivacyDraftError):
    """The requested case draft is not visible to the current RLS actor."""


@dataclass(frozen=True, slots=True)
class TargetReviewPacket:
    target_id: str
    target_name: str
    category: str
    jurisdiction: str
    opt_out_method: str
    approval_tier: ApprovalTier
    approval_reason: str
    legal_basis: str
    required_identifiers: tuple[str, ...]
    available_identity_tuple_types: tuple[str, ...]
    evidence_checklist: tuple[str, ...]
    risk_flags: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "target_id": self.target_id,
            "target_name": self.target_name,
            "category": self.category,
            "jurisdiction": self.jurisdiction,
            "opt_out_method": self.opt_out_method,
            "approval_tier": self.approval_tier,
            "approval_reason": self.approval_reason,
            "legal_basis": self.legal_basis,
            "required_identifiers": list(self.required_identifiers),
            "available_identity_tuple_types": list(self.available_identity_tuple_types),
            "evidence_checklist": list(self.evidence_checklist),
            "risk_flags": list(self.risk_flags),
        }


@dataclass(frozen=True, slots=True)
class CreatedCaseDraft:
    case_draft: StoredCaseDraft
    actions: tuple[StoredDraftAction, ...]
    review_packets: tuple[TargetReviewPacket, ...]


@dataclass(frozen=True, slots=True)
class CaseDraftInboxItem:
    case_draft: StoredCaseDraft
    action_count: int
    approval_tiers: tuple[str, ...]

    @property
    def highest_approval_tier(self) -> str | None:
        return self.approval_tiers[-1] if self.approval_tiers else None


@dataclass(frozen=True, slots=True)
class RetrievedCaseDraft:
    case_draft: StoredCaseDraft
    actions: tuple[StoredDraftAction, ...]
    review_packets: tuple[TargetReviewPacket, ...]

    @property
    def highest_approval_tier(self) -> str | None:
        tiers = sorted({action.approval_tier for action in self.actions})
        return tiers[-1] if tiers else None


class PrivacyCaseDraftRepository:
    """Create encrypted local review packets through an RLS-bound connection."""

    def __init__(self, conn: asyncpg.Connection, crypto: PrivacyCrypto) -> None:
        self._conn = conn
        self._crypto = crypto

    async def create_case_draft(
        self,
        *,
        user_id: str,
        subject_id: UUID,
        target_ids: tuple[str, ...],
    ) -> CreatedCaseDraft:
        normalized_target_ids = _normalize_target_ids(target_ids)
        subject = await get_subject(self._conn, subject_id)
        if subject is None:
            raise PrivacyDraftSubjectNotFound("privacy subject not found")

        tuple_types = await self._active_tuple_types(subject_id)
        targets = []
        for target_id in normalized_target_ids:
            row = await get_target(self._conn, target_id)
            if row is None:
                raise PrivacyDraftTargetNotFound(target_id)
            targets.append(_target_from_cache_row(row))

        policy_subject = _policy_subject(subject)
        review_packets = tuple(
            _build_review_packet(
                target=target,
                subject=policy_subject,
                tuple_types=tuple_types,
            )
            for target in targets
        )
        case_payload = _case_payload(
            subject=subject,
            target_ids=normalized_target_ids,
            tuple_types=tuple_types,
            review_packets=review_packets,
        )
        encrypted_case = self._crypto.encrypt_json_payload(case_payload)

        async with self._conn.transaction():
            case_draft = await insert_case_draft(
                self._conn,
                subject_id=subject_id,
                created_by_user_id=user_id,
                target_count=len(normalized_target_ids),
                packet_payload_ciphertext=encrypted_case.ciphertext,
                packet_payload_hash=encrypted_case.payload_hash,
                payload_key_version=encrypted_case.key_version,
            )
            actions = []
            for packet in review_packets:
                encrypted_action = self._crypto.encrypt_json_payload(
                    {
                        "case_id": str(case_draft.id),
                        "packet_version": "p2e-v1",
                        **packet.to_payload(),
                    }
                )
                action = await insert_draft_action(
                    self._conn,
                    subject_id=subject_id,
                    target_id=packet.target_id,
                    case_draft_id=case_draft.id,
                    action_type=ActionType.DRAFT.value,
                    approval_tier=packet.approval_tier,
                    draft_payload_ciphertext=encrypted_action.ciphertext,
                    draft_payload_hash=encrypted_action.payload_hash,
                    payload_key_version=encrypted_action.key_version,
                )
                await append_action_event(
                    self._conn,
                    action_id=action.id,
                    event_type="created",
                    actor=user_id,
                )
                actions.append(action)

        logger.info(
            "privacy_case_draft_created case_id=%s subject_id=%s target_count=%d",
            case_draft.id,
            subject_id,
            len(actions),
        )
        return CreatedCaseDraft(
            case_draft=case_draft,
            actions=tuple(actions),
            review_packets=review_packets,
        )

    async def list_case_drafts(
        self,
        *,
        limit: int = 25,
    ) -> tuple[CaseDraftInboxItem, ...]:
        rows = await list_case_drafts(self._conn, limit=limit)
        return tuple(_inbox_item(row) for row in rows)

    async def get_case_draft(self, case_id: UUID) -> RetrievedCaseDraft:
        stored_payload = await get_case_draft_payload(self._conn, case_id)
        if stored_payload is None:
            raise PrivacyDraftCaseNotFound("privacy case draft not found")
        if (
            sha256_digest(stored_payload.packet_payload_ciphertext)
            != stored_payload.case_draft.packet_payload_hash
        ):
            raise PrivacyDraftError("privacy case draft payload hash mismatch")

        try:
            packet_payload = self._crypto.decrypt_json_payload(
                EncryptedPayload(
                    ciphertext=stored_payload.packet_payload_ciphertext,
                    payload_hash=stored_payload.case_draft.packet_payload_hash,
                    key_version=stored_payload.case_draft.payload_key_version,
                )
            )
        except ValueError as exc:
            raise PrivacyDraftError("privacy case draft decrypt failed") from exc
        actions = tuple(await list_draft_actions_for_case(self._conn, case_id))
        return RetrievedCaseDraft(
            case_draft=stored_payload.case_draft,
            actions=actions,
            review_packets=_review_packets_from_payload(packet_payload),
        )

    async def _active_tuple_types(self, subject_id: UUID) -> tuple[str, ...]:
        tuples = await list_identity_tuples(self._conn, subject_id, active_only=True)
        return tuple(sorted({item.tuple_type.value for item in tuples}))


def _inbox_item(row: StoredCaseDraftListItem) -> CaseDraftInboxItem:
    return CaseDraftInboxItem(
        case_draft=row.case_draft,
        action_count=row.action_count,
        approval_tiers=row.approval_tiers,
    )


def _normalize_target_ids(target_ids: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(target_id.strip() for target_id in target_ids)
    if not normalized or any(not target_id for target_id in normalized):
        raise PrivacyDraftError("at least one target_id is required")
    if len(set(normalized)) != len(normalized):
        raise PrivacyDraftError("target_ids must be unique")
    return normalized


def _policy_subject(subject: StoredSubject) -> Subject:
    return Subject(
        id=subject.id,
        user_id=subject.user_id,
        display_name="privacy subject",
        role=subject.role,
        jurisdiction=subject.jurisdiction,
        guardian_user_id=subject.guardian_user_id,
        status=subject.status,
        created_at=subject.created_at,
        updated_at=subject.updated_at,
    )


def _target_from_cache_row(row: dict[str, object]) -> Target:
    return Target(
        id=str(row["id"]),
        name=str(row["name"]),
        category=TargetCategory(str(row["category"])),
        jurisdiction=Jurisdiction(str(row["jurisdiction"])),
        opt_out_method=OptOutMethod(str(row["opt_out_method"])),
        opt_out_url=_optional_str(row.get("opt_out_url")),
        contact_email=_optional_str(row.get("contact_email")),
        supports_minors=bool(row.get("supports_minors", False)),
        requires_sensitive_payload=bool(row.get("requires_sensitive_payload", False)),
        requires_identity_document=bool(row.get("requires_identity_document", False)),
        avg_response_days=_optional_int(row.get("avg_response_days")),
        last_verified=row.get("last_verified"),
        notes=_optional_str(row.get("notes")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _build_review_packet(
    *,
    target: Target,
    subject: Subject,
    tuple_types: tuple[str, ...],
) -> TargetReviewPacket:
    decision = evaluate_tier(subject, ActionType.DRAFT, target)
    return TargetReviewPacket(
        target_id=target.id,
        target_name=target.name,
        category=target.category.value,
        jurisdiction=target.jurisdiction.value,
        opt_out_method=target.opt_out_method.value,
        approval_tier=decision.tier,
        approval_reason=decision.reason,
        legal_basis=_legal_basis(target),
        required_identifiers=_required_identifiers(target),
        available_identity_tuple_types=tuple_types,
        evidence_checklist=_evidence_checklist(target),
        risk_flags=_risk_flags(target),
    )


def _legal_basis(target: Target) -> str:
    if target.category == TargetCategory.PUBLIC_RECORD:
        return "Public-record privacy review; court-specific process may be required."
    if target.category == TargetCategory.DATA_BROKER:
        return "Personal data broker opt-out or suppression request."
    if target.category == TargetCategory.SOCIAL:
        return "Profile privacy review or account-controlled removal request."
    return "Exposure review for breach or indexed personal-data reference."


def _required_identifiers(target: Target) -> tuple[str, ...]:
    identifiers = ["full_name_or_name"]
    if target.category == TargetCategory.DATA_BROKER:
        identifiers.extend(["email_or_phone", "address_if_available"])
    elif target.category == TargetCategory.PUBLIC_RECORD:
        identifiers.extend(["jurisdiction", "case_or_record_reference_if_available"])
    elif target.category == TargetCategory.SOCIAL:
        identifiers.extend(["profile_url_or_handle", "account_email_if_available"])
    else:
        identifiers.extend(["email_or_phone", "breach_reference_if_available"])

    if target.requires_identity_document:
        identifiers.append("identity_document_reference")
    return tuple(identifiers)


def _evidence_checklist(target: Target) -> tuple[str, ...]:
    checklist = [
        "Confirm selected subject and target before approval.",
        "Confirm available identity tuple types satisfy target requirements.",
        "Review target method and expected response window.",
    ]
    if target.opt_out_method == OptOutMethod.COURT_MOTION:
        checklist.append("Confirm legal basis and court-specific filing path.")
    if target.requires_sensitive_payload:
        checklist.append("Confirm sensitive payload is required and minimized.")
    if target.requires_identity_document:
        checklist.append("Attach or reference identity document only after T5 review.")
    return tuple(checklist)


def _risk_flags(target: Target) -> tuple[str, ...]:
    flags = []
    if target.opt_out_method == OptOutMethod.COURT_MOTION:
        flags.append("court_motion")
    if target.requires_sensitive_payload:
        flags.append("sensitive_payload")
    if target.requires_identity_document:
        flags.append("identity_document")
    if target.supports_minors:
        flags.append("supports_minors")
    return tuple(flags)


def _case_payload(
    *,
    subject: StoredSubject,
    target_ids: tuple[str, ...],
    tuple_types: tuple[str, ...],
    review_packets: tuple[TargetReviewPacket, ...],
) -> dict[str, object]:
    return {
        "packet_version": "p2e-v1",
        "subject_id": str(subject.id),
        "subject_role": subject.role.value,
        "subject_jurisdiction": subject.jurisdiction,
        "selected_target_ids": list(target_ids),
        "available_identity_tuple_types": list(tuple_types),
        "review_packets": [packet.to_payload() for packet in review_packets],
    }


_APPROVAL_TIERS = {"T1", "T2", "T3", "T4", "T5"}


def _review_packets_from_payload(
    payload: dict[str, object],
) -> tuple[TargetReviewPacket, ...]:
    packet_version = payload.get("packet_version")
    if packet_version != "p2e-v1":
        raise PrivacyDraftError("unsupported privacy case draft packet version")
    raw_packets = payload.get("review_packets")
    if not isinstance(raw_packets, list):
        raise PrivacyDraftError("privacy case draft packets missing")
    return tuple(_review_packet_from_payload(packet) for packet in raw_packets)


def _review_packet_from_payload(packet: object) -> TargetReviewPacket:
    if not isinstance(packet, dict):
        raise PrivacyDraftError("privacy case draft packet invalid")
    return TargetReviewPacket(
        target_id=_payload_str(packet, "target_id"),
        target_name=_payload_str(packet, "target_name"),
        category=_payload_str(packet, "category"),
        jurisdiction=_payload_str(packet, "jurisdiction"),
        opt_out_method=_payload_str(packet, "opt_out_method"),
        approval_tier=_payload_approval_tier(packet.get("approval_tier")),
        approval_reason=_payload_str(packet, "approval_reason"),
        legal_basis=_payload_str(packet, "legal_basis"),
        required_identifiers=_payload_str_tuple(packet, "required_identifiers"),
        available_identity_tuple_types=_payload_str_tuple(
            packet,
            "available_identity_tuple_types",
        ),
        evidence_checklist=_payload_str_tuple(packet, "evidence_checklist"),
        risk_flags=_payload_str_tuple(packet, "risk_flags"),
    )


def _payload_str(packet: dict[object, object], key: str) -> str:
    value = packet.get(key)
    if not isinstance(value, str):
        raise PrivacyDraftError(f"privacy case draft packet missing {key}")
    return value


def _payload_str_tuple(packet: dict[object, object], key: str) -> tuple[str, ...]:
    value = packet.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PrivacyDraftError(f"privacy case draft packet missing {key}")
    return tuple(value)


def _payload_approval_tier(value: object) -> ApprovalTier:
    if not isinstance(value, str) or value not in _APPROVAL_TIERS:
        raise PrivacyDraftError("privacy case draft packet has invalid approval tier")
    return cast(ApprovalTier, value)
