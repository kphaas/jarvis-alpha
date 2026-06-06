from __future__ import annotations

from uuid import uuid4

import pytest

from brain.agents.privacy_scrub.crypto import (
    EncryptedPayload,
    PrivacyCrypto,
    PrivacyCryptoConfig,
    sha256_digest,
)
from brain.agents.privacy_scrub.identity import TupleType


def _crypto() -> PrivacyCrypto:
    return PrivacyCrypto(
        PrivacyCryptoConfig(
            digest_key="test-digest-key",
            digest_key_version="digest-v1",
            payload_key="test-payload-key",
            payload_key_version="payload-v1",
        )
    )


def test_encrypt_json_payload_keeps_plaintext_out_of_ciphertext():
    crypto = _crypto()
    encrypted = crypto.encrypt_json_payload(
        {
            "display_label": "Ken",
            "profile": {"email": "ken@example.com"},
        }
    )

    assert encrypted.ciphertext.startswith(b"privacy-aesgcm:v1:")
    assert b"Ken" not in encrypted.ciphertext
    assert b"ken@example.com" not in encrypted.ciphertext
    assert encrypted.payload_hash == sha256_digest(encrypted.ciphertext)
    assert encrypted.key_version == "payload-v1"


def test_encrypt_json_payload_round_trips_app_side():
    crypto = _crypto()
    encrypted = crypto.encrypt_json_payload(
        {"display_label": "Ken", "profile": {"city": "Atlanta"}}
    )

    assert crypto.decrypt_json_payload(encrypted) == {
        "display_label": "Ken",
        "profile": {"city": "Atlanta"},
    }


def test_decrypt_rejects_unknown_envelope():
    crypto = _crypto()
    with pytest.raises(ValueError, match="unsupported"):
        crypto.decrypt_json_payload(
            EncryptedPayload(
                ciphertext=b"plaintext",
                payload_hash=sha256_digest(b"plaintext"),
                key_version="payload-v1",
            )
        )


def test_crypto_rejects_blank_keys_and_versions():
    with pytest.raises(ValueError, match="digest_key"):
        PrivacyCrypto(
            PrivacyCryptoConfig(
                digest_key="",
                digest_key_version="digest-v1",
                payload_key="payload-key",
                payload_key_version="payload-v1",
            )
        )

    with pytest.raises(ValueError, match="payload_key_version"):
        PrivacyCrypto(
            PrivacyCryptoConfig(
                digest_key="digest-key",
                digest_key_version="digest-v1",
                payload_key="payload-key",
                payload_key_version="",
            )
        )


def test_display_label_digest_is_keyed():
    crypto = _crypto()

    digest = crypto.display_label_digest("Ken")

    assert digest.startswith("hmac-sha256:")
    assert "Ken" not in digest


def test_digest_value_is_keyed_and_namespace_scoped():
    crypto = _crypto()

    digest = crypto.digest_value("search_result_url", "https://example.test/ken")
    other_namespace = crypto.digest_value(
        "evidence_reference", "https://example.test/ken"
    )

    assert digest.startswith("hmac-sha256:")
    assert digest != other_namespace
    assert "example" not in digest


def test_identity_tuple_from_value_uses_digest_key_version():
    crypto = _crypto()
    subject_id = uuid4()

    tuple_obj = crypto.identity_tuple_from_value(
        subject_id,
        TupleType.EMAIL,
        "KEN@example.com",
        label="Primary",
    )

    assert tuple_obj.subject_id == subject_id
    assert tuple_obj.digest.startswith("hmac-sha256:")
    assert tuple_obj.key_version == "digest-v1"
    assert tuple_obj.label_digest is not None
    assert "Primary" not in tuple_obj.label_digest
