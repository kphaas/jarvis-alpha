from __future__ import annotations

import pytest
from uuid import uuid4

from brain.agents.privacy_scrub import config as privacy_config
from brain.agents.privacy_scrub.config import (
    PRIVACY_SCRUB_DIGEST_KEY,
    PRIVACY_SCRUB_DIGEST_KEY_VERSION,
    PRIVACY_SCRUB_PAYLOAD_KEY,
    PRIVACY_SCRUB_PAYLOAD_KEY_VERSION,
    PrivacyScrubConfigError,
    load_privacy_crypto,
)
from brain.agents.privacy_scrub.identity import TupleType


def test_load_privacy_crypto_reads_complete_environment(monkeypatch) -> None:
    monkeypatch.setenv(PRIVACY_SCRUB_DIGEST_KEY, "digest-secret")
    monkeypatch.setenv(PRIVACY_SCRUB_DIGEST_KEY_VERSION, "digest-v1")
    monkeypatch.setenv(PRIVACY_SCRUB_PAYLOAD_KEY, "payload-secret")
    monkeypatch.setenv(PRIVACY_SCRUB_PAYLOAD_KEY_VERSION, "payload-v1")

    crypto = load_privacy_crypto()
    tuple_obj = crypto.identity_tuple_from_value(
        subject_id=uuid4(),
        tuple_type=TupleType.EMAIL,
        raw_value="KEN@example.com",
    )

    assert crypto.digest_key_version == "digest-v1"
    assert crypto.payload_key_version == "payload-v1"
    assert tuple_obj.key_version == "digest-v1"
    assert "KEN@example.com" not in tuple_obj.digest


def test_load_privacy_crypto_fails_closed_when_secret_missing(monkeypatch) -> None:
    for name in (
        PRIVACY_SCRUB_DIGEST_KEY,
        PRIVACY_SCRUB_DIGEST_KEY_VERSION,
        PRIVACY_SCRUB_PAYLOAD_KEY,
        PRIVACY_SCRUB_PAYLOAD_KEY_VERSION,
    ):
        monkeypatch.delenv(name, raising=False)

    def missing_secret(name: str) -> str:
        raise KeyError(name)

    monkeypatch.setattr(privacy_config, "get_secret", missing_secret)

    with pytest.raises(PrivacyScrubConfigError, match="privacy_scrub_config_missing"):
        load_privacy_crypto()


def test_load_privacy_crypto_uses_secret_store_fallback(monkeypatch) -> None:
    values = {
        PRIVACY_SCRUB_DIGEST_KEY: "digest-secret",
        PRIVACY_SCRUB_DIGEST_KEY_VERSION: "digest-v1",
        PRIVACY_SCRUB_PAYLOAD_KEY: "payload-secret",
        PRIVACY_SCRUB_PAYLOAD_KEY_VERSION: "payload-v1",
    }
    for name in values:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(privacy_config, "get_secret", values.__getitem__)

    crypto = load_privacy_crypto()

    assert crypto.digest_key_version == "digest-v1"
    assert crypto.payload_key_version == "payload-v1"
