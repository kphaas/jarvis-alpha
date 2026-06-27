from __future__ import annotations

import pytest

from brain.services import herald_linkedin


@pytest.mark.asyncio
async def test_linkedin_client_posts_through_gateway(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    async def fake_gateway(path: str, payload: dict, *, timeout_s: int):
        calls.append((path, payload))
        return {
            "status_code": 201,
            "post_urn": "urn:li:share:abc123",
            "post_url": "https://www.linkedin.com/feed/update/urn:li:share:abc123",
        }

    monkeypatch.setattr(herald_linkedin, "call_gateway_proxy", fake_gateway)
    client = herald_linkedin.HeraldLinkedInClient(
        access_token="token-" + ("x" * 40),
        author_urn="urn:li:person:abc123",
        linkedin_version="202606",
    )

    result = await client.publish_text("Approved LinkedIn post")

    assert result.status_code == 201
    assert result.provider_post_urn == "urn:li:share:abc123"
    assert calls == [
        (
            "linkedin/member_post",
            {
                "access_token": "token-" + ("x" * 40),
                "author_urn": "urn:li:person:abc123",
                "linkedin_version": "202606",
                "text": "Approved LinkedIn post",
            },
        )
    ]


@pytest.mark.asyncio
async def test_linkedin_client_fails_closed_on_gateway_error(monkeypatch) -> None:
    async def fake_gateway(path: str, payload: dict, *, timeout_s: int):
        return {"status_code": 401, "payload": {"message": "nope"}}

    monkeypatch.setattr(herald_linkedin, "call_gateway_proxy", fake_gateway)
    client = herald_linkedin.HeraldLinkedInClient(
        access_token="token-" + ("x" * 40),
        author_urn="urn:li:person:abc123",
    )

    with pytest.raises(herald_linkedin.HeraldLinkedInPublishError):
        await client.publish_text("Approved LinkedIn post")
