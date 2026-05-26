"""Deterministic redaction helpers for message-bearing domains.

These helpers are intentionally boring: deterministic hashes for correlation,
raw body suppression for logs, and narrow regexes for common contact tokens.
They are not a DLP engine; they are the first production rail that prevents
email/iMessage bodies from leaking into agent logs and ChatOps payloads.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

_EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w.+-])"
)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"
)
_BODY_KEYS = frozenset(
    {
        "body",
        "body_text",
        "content",
        "html",
        "message",
        "raw_body",
        "text",
    }
)


def stable_hash(value: str | bytes | None, *, namespace: str = "alpha") -> str:
    """Return a stable SHA-256 handle that can be logged without raw content."""

    raw = (
        b"" if value is None else value if isinstance(value, bytes) else value.encode()
    )
    digest = hashlib.sha256(namespace.encode() + b"\0" + raw).hexdigest()
    return f"sha256:{digest}"


def short_hash(value: str | bytes | None, *, namespace: str = "alpha") -> str:
    return stable_hash(value, namespace=namespace).split(":", 1)[1][:12]


def redact_contact_tokens(text: str, *, namespace: str = "alpha") -> str:
    """Replace email addresses and phone numbers with deterministic handles."""

    redacted = _EMAIL_RE.sub(
        lambda match: (
            f"[email:{short_hash(match.group(1).lower(), namespace=namespace)}]"
        ),
        text,
    )
    return _PHONE_RE.sub(
        lambda match: (
            f"[phone:{short_hash(_digits_only(match.group(0)), namespace=namespace)}]"
        ),
        redacted,
    )


def redact_message_body(
    body: str | None, *, namespace: str = "alpha"
) -> dict[str, Any]:
    """Summarize a body for logs without retaining raw text."""

    value = body or ""
    return {
        "body_hash": stable_hash(value, namespace=namespace),
        "body_bytes": len(value.encode()),
        "body_redacted": True,
    }


def redact_mapping_for_log(
    payload: Mapping[str, Any], *, namespace: str = "alpha"
) -> dict[str, Any]:
    """Return a shallow log-safe copy of a payload.

    Message-body-like keys become hash metadata. String values in other keys
    keep their shape but redact contact tokens.
    """

    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        normalized = key.lower()
        if normalized in _BODY_KEYS:
            redacted[key] = redact_message_body(
                str(value) if value is not None else None,
                namespace=namespace,
            )
        elif isinstance(value, str):
            redacted[key] = redact_contact_tokens(value, namespace=namespace)
        else:
            redacted[key] = value
    return redacted


def _digits_only(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())
