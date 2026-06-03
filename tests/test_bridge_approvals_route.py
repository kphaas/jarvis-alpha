from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from brain.routes import bridge_approvals
from brain.routes.bridge_approvals import (
    BridgeApprovalSubmitRequest,
    BridgeClaims,
)


def _rsa_pair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def _request_body(**overrides) -> BridgeApprovalSubmitRequest:
    values = {
        "envelope_version": "1.0.0",
        "domain": "jarvis-financial",
        "domain_version": "1.0.0",
        "intent_kind": "trade_proposal",
        "tier_requested": "T2",
        "expires_at_window_seconds": 60,
        "caller_idempotency_key": str(uuid4()),
        "trace_id": str(uuid4()),
        "service_caller": "jarvis-fin-agent",
        "submitted_at": datetime.now(UTC),
        "payload": {
            "symbol": "AAPL",
            "side": "buy",
            "qty": "1",
            "est_value_usd": "200",
        },
    }
    values.update(overrides)
    return BridgeApprovalSubmitRequest(**values)


def _claims() -> BridgeClaims:
    return BridgeClaims(
        sub="jarvis-fin-agent",
        iss="jarvis-fin-agent",
        domain="jarvis-financial",
        domain_version="1.0.0",
    )


def _row(**overrides):
    values = {
        "id": uuid4(),
        "action_class": ["financial_trade", "paper_trade"],
        "risk_tier": "T2",
        "actor_sub": "jarvis-fin-agent",
        "actor_type": "service",
        "description": "Financial paper trade proposal",
        "parameters_hash": "hash",
        "status": "pending",
        "requested_at": datetime.now(UTC),
        "decided_by": None,
        "decided_at": None,
        "expires_at": datetime.now(UTC) + timedelta(minutes=10),
    }
    values.update(overrides)
    return values


class FakeConn:
    def __init__(self, *, existing=None, inserted=None):
        self.existing = existing
        self.inserted = inserted or _row()
        self.fetchrow_calls = []
        self.fetchval_calls = []

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        if "WHERE nonce" in query:
            return self.existing
        return self.inserted

    async def fetchval(self, query, *args):
        self.fetchval_calls.append((query, args))
        return self.inserted["id"]


def test_require_financial_bridge_service_accepts_valid_token(monkeypatch, tmp_path):
    private_pem, public_pem = _rsa_pair()
    public_path = tmp_path / "financial_public.pem"
    public_path.write_text(public_pem, encoding="utf-8")
    monkeypatch.setenv("ALPHA_BRIDGE_FINANCIAL_PUBLIC_KEY_PATH", str(public_path))
    token = jwt.encode(
        {
            "iss": "jarvis-fin-agent",
            "sub": "jarvis-fin-agent",
            "aud": "jarvis-alpha-bridge",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": datetime.now(UTC),
            "domain": "jarvis-financial",
            "domain_version": "1.0.0",
        },
        private_pem,
        algorithm="RS256",
    )
    request = SimpleNamespace(headers={"Authorization": f"Bearer {token}"})

    claims = bridge_approvals._require_financial_bridge_service(request)

    assert claims.sub == "jarvis-fin-agent"
    assert claims.domain == "jarvis-financial"


def test_require_financial_bridge_service_rejects_wrong_audience(monkeypatch, tmp_path):
    private_pem, public_pem = _rsa_pair()
    public_path = tmp_path / "financial_public.pem"
    public_path.write_text(public_pem, encoding="utf-8")
    monkeypatch.setenv("ALPHA_BRIDGE_FINANCIAL_PUBLIC_KEY_PATH", str(public_path))
    token = jwt.encode(
        {
            "iss": "jarvis-fin-agent",
            "sub": "jarvis-fin-agent",
            "aud": "wrong",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": datetime.now(UTC),
            "domain": "jarvis-financial",
        },
        private_pem,
        algorithm="RS256",
    )
    request = SimpleNamespace(headers={"Authorization": f"Bearer {token}"})

    with pytest.raises(HTTPException) as exc:
        bridge_approvals._require_financial_bridge_service(request)

    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid_bridge_token"


@pytest.mark.asyncio
async def test_submit_bridge_approval_queues_new_request(monkeypatch):
    conn = FakeConn(inserted=_row(status="pending"))

    @asynccontextmanager
    async def fake_rls_context_connection(ctx):
        yield conn

    monkeypatch.setattr(
        bridge_approvals,
        "rls_context_connection",
        fake_rls_context_connection,
    )

    response = await bridge_approvals.submit_bridge_approval(_request_body(), _claims())

    assert response.status == "pending"
    assert response.tier_assigned == "T2"
    assert conn.fetchval_calls
    args = conn.fetchval_calls[0][1]
    assert args[0] == ["financial_trade", "paper_trade"]
    assert args[2] == "jarvis-fin-agent"
    assert args[3] == "service"


@pytest.mark.asyncio
async def test_submit_bridge_approval_reuses_existing_request(monkeypatch):
    conn = FakeConn(existing=_row(status="pending"))

    @asynccontextmanager
    async def fake_rls_context_connection(ctx):
        yield conn

    monkeypatch.setattr(
        bridge_approvals,
        "rls_context_connection",
        fake_rls_context_connection,
    )

    response = await bridge_approvals.submit_bridge_approval(_request_body(), _claims())

    assert response.status == "pending"
    assert conn.fetchval_calls == []


@pytest.mark.asyncio
async def test_get_bridge_approval_returns_intent_token_for_approved_row(
    monkeypatch, tmp_path
):
    private_pem, public_pem = _rsa_pair()
    private_path = tmp_path / "alpha_private.pem"
    private_path.write_text(private_pem, encoding="utf-8")
    monkeypatch.setenv("ALPHA_JWT_PRIVATE_KEY", str(private_path))
    approved = _row(status="approved", decided_by="ken", decided_at=datetime.now(UTC))
    conn = FakeConn(inserted=approved)

    @asynccontextmanager
    async def fake_rls_context_connection(ctx):
        yield conn

    monkeypatch.setattr(
        bridge_approvals,
        "rls_context_connection",
        fake_rls_context_connection,
    )

    response = await bridge_approvals.get_bridge_approval(approved["id"], _claims())

    assert response.status == "approved"
    assert response.intent_token is not None
    decoded = jwt.decode(
        response.intent_token,
        public_pem,
        algorithms=["RS256"],
        audience="jarvis-financial",
    )
    assert decoded["approval_id"] == str(approved["id"])
    assert decoded["intent_kind"] == "trade_proposal"
