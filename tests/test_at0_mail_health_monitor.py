from __future__ import annotations

import base64
import json

import pytest

from brain.services.at0_mail_health import decode_graph_roles, required_graph_roles


def _token(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
    body = encoded.decode("ascii").rstrip("=")
    return f"header.{body}.signature"


def test_decode_graph_roles_sorts_roles() -> None:
    token = _token({"roles": ["Mail.Send", "Mail.Read", "Mail.Send"]})

    assert decode_graph_roles(token) == ["Mail.Read", "Mail.Send", "Mail.Send"]


def test_decode_graph_roles_rejects_malformed_token() -> None:
    with pytest.raises(Exception, match="graph_token_claims_unreadable"):
        decode_graph_roles("not-a-jwt")


def test_required_graph_roles_defaults_to_mail_send() -> None:
    assert required_graph_roles("") == ("Mail.Send",)
    assert required_graph_roles("Mail.Send, Mail.Read") == ("Mail.Send", "Mail.Read")
