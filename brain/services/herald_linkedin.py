from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from brain.config.secrets import get_secret
from brain.services.gateway_egress import GatewayEgressError, call_gateway_proxy


class HeraldLinkedInConfigError(RuntimeError):
    pass


class HeraldLinkedInPublishError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class HeraldLinkedInPublishResult:
    status_code: int
    provider_post_urn: str | None
    published_url: str | None


def _secret(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        return get_secret(name).strip()
    except Exception:
        return default


def _required_secret(name: str) -> str:
    value = _secret(name)
    if not value:
        raise HeraldLinkedInConfigError(f"{name} is not configured")
    return value


class HeraldLinkedInClient:
    def __init__(
        self,
        *,
        access_token: str | None = None,
        author_urn: str | None = None,
        linkedin_version: str | None = None,
    ) -> None:
        self.access_token = access_token or _required_secret(
            "AT0_LINKEDIN_ACCESS_TOKEN"
        )
        self.author_urn = author_urn or _required_secret("AT0_LINKEDIN_AUTHOR_URN")
        self.linkedin_version = linkedin_version or _secret(
            "AT0_LINKEDIN_API_VERSION", "202606"
        )

    async def publish_text(self, text: str) -> HeraldLinkedInPublishResult:
        clean = " ".join(text.split()).strip()
        if not clean:
            raise HeraldLinkedInPublishError("linkedin_post_text_empty")
        if len(clean) > 3000:
            raise HeraldLinkedInPublishError("linkedin_post_text_too_long")
        try:
            response = await call_gateway_proxy(
                "linkedin/member_post",
                {
                    "access_token": self.access_token,
                    "author_urn": self.author_urn,
                    "linkedin_version": self.linkedin_version,
                    "text": clean,
                },
                timeout_s=35,
            )
        except GatewayEgressError as exc:
            raise HeraldLinkedInPublishError(f"LinkedIn publish failed: {exc}") from exc

        status_code = int(response.get("status_code") or 502)
        if status_code not in {200, 201}:
            raise HeraldLinkedInPublishError(
                f"LinkedIn publish failed: {status_code}",
                status_code=status_code,
            )
        return HeraldLinkedInPublishResult(
            status_code=status_code,
            provider_post_urn=_optional_str(response.get("post_urn")),
            published_url=_optional_str(response.get("post_url")),
        )


async def publish_linkedin_text(text: str) -> HeraldLinkedInPublishResult:
    return await HeraldLinkedInClient().publish_text(text)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
