from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _load_operator() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "financial_approval_operator.py"
    )
    spec = importlib.util.spec_from_file_location("financial_approval_operator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load financial_approval_operator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


operator = _load_operator()


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


def test_base_url_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_ALPHA_BASE_URL", "https://alpha.test/")

    assert operator._base_url(None) == "https://alpha.test"


def test_is_financial_paper_requires_actor_and_actions() -> None:
    assert operator._is_financial_paper(
        {
            "actor_sub": "jarvis-fin-agent",
            "action_class": ["financial_trade", "paper_trade"],
        }
    )
    assert not operator._is_financial_paper(
        {
            "actor_sub": "other",
            "action_class": ["financial_trade", "paper_trade"],
        }
    )
    assert not operator._is_financial_paper(
        {
            "actor_sub": "jarvis-fin-agent",
            "action_class": ["financial_trade"],
        }
    )


def test_select_pending_by_explicit_approval_id() -> None:
    item = {"id": "approval-1", "actor_sub": "other", "action_class": []}

    assert (
        operator._select_pending(
            [item],
            approval_id="approval-1",
            latest_financial_paper=False,
        )
        is item
    )


def test_select_pending_latest_financial_paper_uses_latest_match() -> None:
    first = {
        "id": "first",
        "actor_sub": "jarvis-fin-agent",
        "action_class": ["financial_trade", "paper_trade"],
    }
    second = {
        "id": "second",
        "actor_sub": "jarvis-fin-agent",
        "action_class": ["paper_trade", "financial_trade"],
    }

    assert (
        operator._select_pending(
            [first, {"id": "ignore"}, second],
            approval_id=None,
            latest_financial_paper=True,
        )
        is second
    )


def test_select_pending_requires_selector() -> None:
    with pytest.raises(RuntimeError, match="pass --approval-id"):
        operator._select_pending([], approval_id=None, latest_financial_paper=False)


def test_mint_admin_token_uses_admin_claims(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    private_pem, public_pem = _rsa_pair()
    private_path = tmp_path / "jwt_private.pem"
    private_path.write_text(private_pem, encoding="utf-8")
    monkeypatch.setenv("ALPHA_JWT_PRIVATE_KEY", str(private_path))

    token = operator._mint_admin_token(profile_id="ken")
    decoded = jwt.decode(token, public_pem, algorithms=["RS256"])

    assert decoded["sub"] == "ken"
    assert decoded["iss"] == "user"
    assert decoded["role"] == "admin"
    assert decoded["actor_type"] == "user"
    assert decoded["scopes"] == ["*"]


def test_mint_approval_token_uses_approval_purpose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    private_pem, public_pem = _rsa_pair()
    private_path = tmp_path / "jwt_private.pem"
    private_path.write_text(private_pem, encoding="utf-8")
    monkeypatch.setenv("ALPHA_JWT_PRIVATE_KEY", str(private_path))

    token = operator._mint_approval_token(profile_id="ken")
    decoded = jwt.decode(token, public_pem, algorithms=["RS256"])

    assert decoded["sub"] == "ken"
    assert decoded["purpose"] == "approval"
