"""Repository helpers for privacy-scrub P2-A intake.

This layer accepts plaintext intake values, converts them with PrivacyCrypto,
and delegates only storage-safe values to state.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import asyncpg

from brain.agents.privacy_scrub.crypto import PrivacyCrypto
from brain.agents.privacy_scrub.identity import TupleType
from brain.agents.privacy_scrub.state import (
    StoredSubject,
    get_subject,
    insert_identity_tuple,
    insert_subject,
)
from brain.agents.privacy_scrub.subjects import Role
from jarvis_common.logging_config import get_logger

logger = get_logger("privacy_scrub.repository")


@dataclass(frozen=True, slots=True)
class IdentityTupleInput:
    tuple_type: TupleType
    raw_value: str
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.raw_value.strip():
            raise ValueError("raw_value is required")


@dataclass(frozen=True, slots=True)
class SubjectIntake:
    user_id: str
    display_label: str
    role: Role
    payload: dict[str, object]
    identity_tuples: tuple[IdentityTupleInput, ...]
    guardian_user_id: str | None = None
    jurisdiction: str = "US_GA"

    def __post_init__(self) -> None:
        if self.role == Role.MINOR and not self.guardian_user_id:
            raise ValueError("minor subject requires guardian_user_id")
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if not self.display_label.strip():
            raise ValueError("display_label is required")
        if not self.identity_tuples:
            raise ValueError("at least one identity tuple is required")


@dataclass(frozen=True, slots=True)
class CreatedSubject:
    subject: StoredSubject
    identity_tuple_ids: tuple[UUID, ...] = field(default_factory=tuple)


class PrivacySubjectRepository:
    """Write privacy subjects through an RLS-bound asyncpg connection."""

    def __init__(self, conn: asyncpg.Connection, crypto: PrivacyCrypto) -> None:
        self._conn = conn
        self._crypto = crypto

    async def create_subject(self, intake: SubjectIntake) -> CreatedSubject:
        async with self._conn.transaction():
            encrypted = self._crypto.encrypt_json_payload(
                _subject_payload_for_storage(intake)
            )
            subject_id = await insert_subject(
                self._conn,
                user_id=intake.user_id,
                display_label_digest=self._crypto.display_label_digest(
                    intake.display_label
                ),
                role=intake.role,
                guardian_user_id=intake.guardian_user_id,
                jurisdiction=intake.jurisdiction,
                subject_payload_ciphertext=encrypted.ciphertext,
                subject_payload_hash=encrypted.payload_hash,
                subject_payload_key_version=encrypted.key_version,
            )
            tuple_ids = []
            for tuple_input in intake.identity_tuples:
                tuple_obj = self._crypto.identity_tuple_from_value(
                    subject_id,
                    tuple_input.tuple_type,
                    tuple_input.raw_value,
                    label=tuple_input.label,
                )
                tuple_id = await insert_identity_tuple(self._conn, tuple_obj)
                if tuple_id is not None:
                    tuple_ids.append(tuple_id)

            stored = await get_subject(self._conn, subject_id)
            if stored is None:
                raise RuntimeError(
                    "privacy subject insert did not return readable subject"
                )

        logger.info(
            "privacy_subject_created subject_id=%s role=%s tuple_count=%d",
            subject_id,
            intake.role.value,
            len(tuple_ids),
        )
        return CreatedSubject(
            subject=stored,
            identity_tuple_ids=tuple(tuple_ids),
        )


def _subject_payload_for_storage(intake: SubjectIntake) -> dict[str, object]:
    return {
        "display_label": intake.display_label,
        "role": intake.role.value,
        "jurisdiction": intake.jurisdiction,
        "guardian_user_id": intake.guardian_user_id,
        "profile": intake.payload,
    }
