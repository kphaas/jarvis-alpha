from __future__ import annotations

import os
from urllib.parse import urlparse

FAMILY_API_URL_ENV = "JARVIS_FAMILY_API_URL"
FAMILY_TAILNET_SUFFIX = ".tail40ed36.ts.net"


class FamilyApiConfigError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def family_api_base_url(
    base_url: str | None = None,
    *,
    env_name: str = FAMILY_API_URL_ENV,
) -> str:
    raw_value = base_url if base_url is not None else os.environ.get(env_name, "")
    value = raw_value.strip()
    if not value:
        raise FamilyApiConfigError(
            code="family_api_not_configured",
            message=f"{env_name} is not configured",
        )

    parsed = urlparse(value)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host.endswith(FAMILY_TAILNET_SUFFIX):
        raise FamilyApiConfigError(
            code="family_api_url_invalid",
            message=f"{env_name} must use an https tailnet host",
        )

    return value.rstrip("/")


def family_api_verify_tls() -> bool:
    return True
