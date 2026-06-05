"""App-side crypto helpers for privacy-scrub intake.

P2-A keeps plaintext at the authenticated boundary. This module turns that
plaintext into storage-safe bytes and keyed digests before the repository layer
touches Postgres.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from brain.agents.privacy_scrub.identity import (
    IdentityTuple,
    TupleType,
    privacy_digest,
)

_ENVELOPE_PREFIX = b"privacy-aesgcm:v1:"
_NONCE_BYTES = 12


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    ciphertext: bytes
    payload_hash: str
    key_version: str


@dataclass(frozen=True, slots=True)
class PrivacyCryptoConfig:
    digest_key: str
    digest_key_version: str
    payload_key: str
    payload_key_version: str


class PrivacyCrypto:
    """Prepare privacy-scrub data for storage.

    The digest key and payload key are intentionally constructor inputs. P2-A
    does not read environment variables or seed secrets because no route or
    runner is active yet.
    """

    def __init__(self, config: PrivacyCryptoConfig) -> None:
        self._digest_key = _require_non_empty(config.digest_key, "digest_key")
        self.digest_key_version = _require_non_empty(
            config.digest_key_version,
            "digest_key_version",
        )
        self._payload_key = _derive_aes_key(
            _require_non_empty(config.payload_key, "payload_key")
        )
        self.payload_key_version = _require_non_empty(
            config.payload_key_version,
            "payload_key_version",
        )

    def display_label_digest(self, display_label: str) -> str:
        return privacy_digest(
            "display_label",
            _require_non_empty(display_label.strip(), "display_label"),
            digest_key=self._digest_key,
        )

    def identity_tuple_from_value(
        self,
        subject_id: UUID,
        tuple_type: TupleType,
        raw_value: str,
        *,
        label: str | None = None,
    ) -> IdentityTuple:
        return IdentityTuple.from_value(
            subject_id,
            tuple_type,
            raw_value,
            digest_key=self._digest_key,
            key_version=self.digest_key_version,
            label=label,
        )

    def encrypt_json_payload(self, payload: Mapping[str, object]) -> EncryptedPayload:
        plaintext = _canonical_json(payload)
        nonce = os.urandom(_NONCE_BYTES)
        aad = self.payload_key_version.encode("utf-8")
        ciphertext = AESGCM(self._payload_key).encrypt(nonce, plaintext, aad)
        envelope = _ENVELOPE_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext)
        return EncryptedPayload(
            ciphertext=envelope,
            payload_hash=sha256_digest(envelope),
            key_version=self.payload_key_version,
        )

    def decrypt_json_payload(self, payload: EncryptedPayload) -> dict[str, object]:
        """Round-trip helper for tests and future app-side review flows.

        No SQL decrypt helper is created by P2-A.
        """

        if not payload.ciphertext.startswith(_ENVELOPE_PREFIX):
            raise ValueError("unsupported privacy payload envelope")
        encoded = payload.ciphertext.removeprefix(_ENVELOPE_PREFIX)
        raw = base64.urlsafe_b64decode(encoded)
        nonce = raw[:_NONCE_BYTES]
        ciphertext = raw[_NONCE_BYTES:]
        aad = payload.key_version.encode("utf-8")
        plaintext = AESGCM(self._payload_key).decrypt(nonce, ciphertext, aad)
        decoded = json.loads(plaintext.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("privacy payload must decrypt to a JSON object")
        return decoded


def sha256_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _derive_aes_key(payload_key: str) -> bytes:
    return hashlib.sha256(payload_key.encode("utf-8")).digest()


def _require_non_empty(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} is required")
    return value
