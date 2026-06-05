"""Identity tuple normalization and keyed digests.

Raw identifiers never persist. The storage layer only receives keyed HMAC
digests so database dumps cannot be used as an offline dictionary of names,
phones, addresses, emails, or dates of birth.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from uuid import UUID


class TupleType(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    NAME = "name"
    FULL_NAME = "full_name"
    DOB = "dob"


def normalize_email(value: str) -> str:
    """Lowercase + strip whitespace; keep plus tags distinct."""
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    """Strip every non-digit. Remove leading US country prefix on 11 digits."""
    digits = "".join(c for c in value if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def normalize_address(value: str) -> str:
    return " ".join(value.strip().lower().split())


def normalize_dob(value: str) -> str:
    return value.strip()


def _default_normalize(value: str) -> str:
    return value.strip()


_NORMALIZERS: dict[TupleType, Callable[[str], str]] = {
    TupleType.EMAIL: normalize_email,
    TupleType.PHONE: normalize_phone,
    TupleType.NAME: normalize_name,
    TupleType.FULL_NAME: normalize_name,
    TupleType.ADDRESS: normalize_address,
    TupleType.DOB: normalize_dob,
}


@dataclass(frozen=True, slots=True)
class IdentityTuple:
    """A persisted-safe identity handle for a subject."""

    id: UUID | None
    subject_id: UUID
    tuple_type: TupleType
    digest: str
    key_version: str
    label_digest: str | None = None
    active: bool = True

    @classmethod
    def from_value(
        cls,
        subject_id: UUID,
        tuple_type: TupleType,
        raw_value: str,
        *,
        digest_key: str,
        key_version: str,
        label: str | None = None,
    ) -> "IdentityTuple":
        """Normalize and HMAC an identifier, discarding the raw value."""
        if not digest_key:
            raise ValueError("digest_key is required")
        if not key_version:
            raise ValueError("key_version is required")
        normalizer = _NORMALIZERS.get(tuple_type, _default_normalize)
        normalized = normalizer(raw_value)
        return cls(
            id=None,
            subject_id=subject_id,
            tuple_type=tuple_type,
            digest=privacy_digest(
                tuple_type.value,
                normalized,
                digest_key=digest_key,
            ),
            key_version=key_version,
            label_digest=(
                privacy_digest("label", normalize_name(label), digest_key=digest_key)
                if label
                else None
            ),
            active=True,
        )


def privacy_digest(namespace: str, value: str, *, digest_key: str) -> str:
    if not digest_key:
        raise ValueError("digest_key is required")
    message = f"{namespace}\0{value}".encode("utf-8")
    digest = hmac.new(
        digest_key.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"
