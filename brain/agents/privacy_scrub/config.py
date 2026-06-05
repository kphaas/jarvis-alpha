"""Runtime configuration for privacy-scrub intake routes."""

from __future__ import annotations

import os

from brain.agents.privacy_scrub.crypto import PrivacyCrypto, PrivacyCryptoConfig
from brain.config.secrets import get_secret

PRIVACY_SCRUB_DIGEST_KEY = "PRIVACY_SCRUB_DIGEST_KEY"
PRIVACY_SCRUB_DIGEST_KEY_VERSION = "PRIVACY_SCRUB_DIGEST_KEY_VERSION"
PRIVACY_SCRUB_PAYLOAD_KEY = "PRIVACY_SCRUB_PAYLOAD_KEY"
PRIVACY_SCRUB_PAYLOAD_KEY_VERSION = "PRIVACY_SCRUB_PAYLOAD_KEY_VERSION"


class PrivacyScrubConfigError(RuntimeError):
    """Raised when intake crypto cannot be configured safely."""


def load_privacy_crypto() -> PrivacyCrypto:
    """Load request-time crypto config from env or the configured secrets file."""

    values = {
        PRIVACY_SCRUB_DIGEST_KEY: _secret(PRIVACY_SCRUB_DIGEST_KEY),
        PRIVACY_SCRUB_DIGEST_KEY_VERSION: _secret(PRIVACY_SCRUB_DIGEST_KEY_VERSION),
        PRIVACY_SCRUB_PAYLOAD_KEY: _secret(PRIVACY_SCRUB_PAYLOAD_KEY),
        PRIVACY_SCRUB_PAYLOAD_KEY_VERSION: _secret(PRIVACY_SCRUB_PAYLOAD_KEY_VERSION),
    }
    missing = [name for name, value in values.items() if not value.strip()]
    if missing:
        raise PrivacyScrubConfigError("privacy_scrub_config_missing")

    try:
        return PrivacyCrypto(
            PrivacyCryptoConfig(
                digest_key=values[PRIVACY_SCRUB_DIGEST_KEY],
                digest_key_version=values[PRIVACY_SCRUB_DIGEST_KEY_VERSION],
                payload_key=values[PRIVACY_SCRUB_PAYLOAD_KEY],
                payload_key_version=values[PRIVACY_SCRUB_PAYLOAD_KEY_VERSION],
            )
        )
    except ValueError as exc:
        raise PrivacyScrubConfigError("privacy_scrub_config_invalid") from exc


def _secret(name: str) -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    try:
        return get_secret(name)
    except KeyError:
        return ""
