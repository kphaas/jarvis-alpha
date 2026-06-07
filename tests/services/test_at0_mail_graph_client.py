from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from brain.services.at0_mail_graph_client import (
    At0MailGraphClient,
    build_client_assertion,
    configured_mailboxes,
    parse_graph_message,
)


def _private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def test_configured_mailboxes_defaults_to_hello_and_support(monkeypatch) -> None:
    monkeypatch.delenv("AT0_HERALD_MAILBOXES", raising=False)

    assert configured_mailboxes() == ("hello@at-0.com", "support@at-0.com")


def test_build_client_assertion_targets_tenant_token_endpoint() -> None:
    assertion = build_client_assertion(
        tenant_id="tenant-id",
        client_id="client-id",
        private_key_pem=_private_key_pem(),
        certificate_x5t="thumbprint",
        now=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
    )
    payload = jwt.decode(assertion, options={"verify_signature": False})
    headers = jwt.get_unverified_header(assertion)

    assert payload["aud"] == (
        "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token"
    )
    assert payload["iss"] == "client-id"
    assert payload["sub"] == "client-id"
    assert headers["x5t"] == "thumbprint"


def test_parse_graph_message_keeps_preview_not_full_body() -> None:
    message = parse_graph_message(
        "hello@at-0.com",
        {
            "id": "graph-1",
            "internetMessageId": "<msg@example.com>",
            "conversationId": "conv-1",
            "from": {
                "emailAddress": {
                    "name": "Casey",
                    "address": "casey@example.com",
                }
            },
            "subject": "Demo",
            "receivedDateTime": "2026-06-07T15:30:00Z",
            "bodyPreview": "  Interested   in AT-0.  ",
            "webLink": "https://outlook.office.com/mail/id/graph-1",
        },
    )

    assert message.graph_message_id == "graph-1"
    assert message.sender_email == "casey@example.com"
    assert message.received_at == datetime(2026, 6, 7, 15, 30, tzinfo=UTC)
    assert message.body_preview == "Interested in AT-0."
    assert len(message.body_preview_sha256) == 64


@pytest.mark.asyncio
async def test_graph_client_uses_gateway_for_token_and_mail(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    async def fake_gateway(path: str, payload: dict, *, timeout_s: int):
        calls.append((path, payload))
        if path == "msgraph/token":
            return {"status_code": 200, "payload": {"access_token": "token"}}
        if path == "msgraph/mailbox_messages":
            return {
                "status_code": 200,
                "payload": {
                    "value": [
                        {
                            "id": "graph-1",
                            "from": {
                                "emailAddress": {
                                    "name": "Casey",
                                    "address": "casey@example.com",
                                }
                            },
                            "subject": "Founding access",
                            "receivedDateTime": "2026-06-07T15:30:00Z",
                            "bodyPreview": "Can I sign up?",
                        }
                    ]
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(
        "brain.services.at0_mail_graph_client.call_gateway_proxy",
        fake_gateway,
    )
    client = At0MailGraphClient(
        tenant_id="tenant-id",
        client_id="client-id",
        private_key_pem=_private_key_pem(),
        certificate_x5t="thumbprint",
    )

    messages = await client.list_messages(mailbox="hello@at-0.com", max_results=1)

    assert messages[0].subject == "Founding access"
    assert [path for path, _payload in calls] == [
        "msgraph/token",
        "msgraph/mailbox_messages",
    ]
    assert calls[1][1]["mailbox"] == "hello@at-0.com"
    assert calls[1][1]["access_token"] == "token"
