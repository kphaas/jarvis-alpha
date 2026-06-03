from __future__ import annotations

import os
from urllib.parse import quote, urlsplit, urlunsplit

from jarvis_common.secrets import get_secret

WRITER_ROLE = "jarvis_alpha_writer"
WRITER_PASSWORD_SECRET = "ALPHA_WRITER_DB_PASSWORD"


def ensure_writer_password(dsn: str) -> str:
    """Return a writer DSN that is ready for password-based local Postgres auth.

    Existing password-bearing DSNs pass through unchanged. Passwordless DSNs for
    non-writer roles also pass through unchanged so admin/migration paths remain
    explicit and easy to audit.
    """

    cleaned = dsn.strip().strip('"').strip("'")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"postgres", "postgresql"}:
        return cleaned
    if parsed.username != WRITER_ROLE or parsed.password is not None:
        return cleaned

    password = os.getenv(WRITER_PASSWORD_SECRET)
    if not password:
        password = get_secret(WRITER_PASSWORD_SECRET)
    password = password.strip().strip('"').strip("'")
    if not password:
        return cleaned

    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    netloc = f"{quote(parsed.username, safe='')}:{quote(password, safe='')}@{host}"
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )
