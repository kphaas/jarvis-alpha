from __future__ import annotations

from uuid import uuid4

import pytest

from brain.agents.privacy_scrub.identity import (
    IdentityTuple,
    TupleType,
    normalize_address,
    normalize_email,
    normalize_name,
    normalize_phone,
    privacy_digest,
)

_KEY = "test-digest-key"


def test_email_normalization_lowercase_and_strip():
    assert normalize_email("  Ken@Example.COM  ") == "ken@example.com"


def test_email_preserves_plus_tags():
    assert normalize_email("ken+work@example.com") != normalize_email("ken@example.com")


def test_phone_normalization_strips_nondigits():
    assert normalize_phone("+1 (404) 555-0100") == "4045550100"
    assert normalize_phone("1-404-555-0100") == "4045550100"


def test_name_normalization():
    assert normalize_name("  Ken   HAAS  ") == "ken haas"


def test_address_normalization():
    assert normalize_address("  123  Main   ST,  Atlanta  GA  ") == (
        "123 main st, atlanta ga"
    )


def test_privacy_digest_is_keyed_and_deterministic():
    a = privacy_digest("email", "ken@example.com", digest_key=_KEY)
    b = privacy_digest("email", "ken@example.com", digest_key=_KEY)
    c = privacy_digest("email", "ken@example.com", digest_key="other-key")

    assert a == b
    assert a != c
    assert a.startswith("hmac-sha256:")


def test_privacy_digest_rejects_blank_key():
    with pytest.raises(ValueError, match="digest_key"):
        privacy_digest("email", "ken@example.com", digest_key="")


def test_from_value_hash_invariant_under_normalization():
    sid = uuid4()
    a = IdentityTuple.from_value(
        sid,
        TupleType.EMAIL,
        "ken@example.com",
        digest_key=_KEY,
        key_version="v1",
    )
    b = IdentityTuple.from_value(
        sid,
        TupleType.EMAIL,
        "  KEN@example.COM  ",
        digest_key=_KEY,
        key_version="v1",
    )
    assert a.digest == b.digest


def test_from_value_keeps_label_out_of_plaintext_shape():
    sid = uuid4()
    item = IdentityTuple.from_value(
        sid,
        TupleType.EMAIL,
        "ken@example.com",
        digest_key=_KEY,
        key_version="v1",
        label="Primary Email",
    )

    assert item.id is None
    assert item.active is True
    assert item.key_version == "v1"
    assert item.label_digest is not None
    assert "Primary" not in item.label_digest
