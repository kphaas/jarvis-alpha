#!/usr/bin/env python3
"""Operator CLI for Financial paper-trade approvals.

This is the supported replacement for direct DB calls during Financial
paper-order probes. It uses the Alpha HTTP approval surface:

    /v1/auth/pin -> /v1/approvals/unlock -> /v1/approvals/{id}/decide

Secrets are read from the environment or prompted; PINs and tokens are never
printed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
import jwt

_DEFAULT_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
_DEFAULT_PRIVATE_KEY = "~/jarvis/pki/jwt/jwt_private.pem"
_FINANCIAL_ACTIONS = {"financial_trade", "paper_trade"}
_TOKEN_TTL_SECONDS = 300


def _base_url(raw: str | None) -> str:
    value = (
        raw
        or os.environ.get("JARVIS_ALPHA_BASE_URL")
        or os.environ.get("ALPHA_BASE_URL")
        or _DEFAULT_BASE_URL
    )
    return value.rstrip("/")


def _pin(raw: str | None) -> str:
    value = raw or os.environ.get("ALPHA_PIN")
    if value:
        return value
    return getpass.getpass("Alpha approval PIN: ")


def _is_financial_paper(item: dict[str, Any]) -> bool:
    action_class = item.get("action_class") or []
    return str(
        item.get("actor_sub")
    ) == "jarvis-fin-agent" and _FINANCIAL_ACTIONS.issubset(
        {str(value) for value in action_class}
    )


def _select_pending(
    pending: list[dict[str, Any]],
    *,
    approval_id: str | None,
    latest_financial_paper: bool,
) -> dict[str, Any]:
    if approval_id:
        match = next(
            (item for item in pending if str(item.get("id")) == approval_id), None
        )
        if match is None:
            raise RuntimeError(f"approval id {approval_id} is not pending")
        return match

    if latest_financial_paper:
        matches = [item for item in pending if _is_financial_paper(item)]
        if not matches:
            raise RuntimeError("no pending Financial paper approvals")
        return matches[-1]

    raise RuntimeError("pass --approval-id or --latest-financial-paper")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _private_key() -> str:
    path = os.environ.get("ALPHA_JWT_PRIVATE_KEY", _DEFAULT_PRIVATE_KEY)
    return Path(path).expanduser().read_text(encoding="utf-8")


def _mint_admin_token(*, profile_id: str) -> str:
    now = int(time.time())
    claims = {
        "sub": profile_id,
        "iss": "user",
        "role": "admin",
        "profile_id": profile_id,
        "workspace_id": "personal",
        "display_name": profile_id,
        "actor_type": "user",
        "max_rating": "adult",
        "scopes": ["*"],
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + _TOKEN_TTL_SECONDS,
    }
    return jwt.encode(claims, _private_key(), algorithm="RS256")


def _mint_approval_token(*, profile_id: str) -> str:
    now = int(time.time())
    claims = {
        "sub": profile_id,
        "purpose": "approval",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + _TOKEN_TTL_SECONDS,
    }
    return jwt.encode(claims, _private_key(), algorithm="RS256")


async def _admin_token(
    client: httpx.AsyncClient,
    *,
    pin: str,
    profile_id: str,
) -> str:
    response = await client.post(
        "/v1/auth/pin", json={"pin": pin, "profile_id": profile_id}
    )
    _raise_for_response(response)
    body = response.json()
    token = body.get("token")
    if not token:
        raise RuntimeError("Alpha auth response did not include token")
    return str(token)


async def _approval_token(client: httpx.AsyncClient, *, pin: str) -> str:
    response = await client.post("/v1/approvals/unlock", json={"pin": pin})
    _raise_for_response(response)
    body = response.json()
    token = body.get("approval_token")
    if not token:
        raise RuntimeError(
            "Alpha approval unlock response did not include approval_token"
        )
    return str(token)


async def _pending(
    client: httpx.AsyncClient, *, admin_token: str
) -> list[dict[str, Any]]:
    response = await client.get("/v1/approvals/pending", headers=_headers(admin_token))
    _raise_for_response(response)
    body = response.json()
    return list(body.get("pending") or [])


async def _decide(
    client: httpx.AsyncClient,
    *,
    admin_token: str,
    approval_token: str,
    queue_id: str,
    decision: Literal["approved", "denied"],
) -> dict[str, Any]:
    headers = {**_headers(admin_token), "X-Approval-Token": approval_token}
    response = await client.post(
        f"/v1/approvals/{queue_id}/decide",
        headers=headers,
        json={"decision": decision},
    )
    _raise_for_response(response)
    return dict(response.json())


def _raise_for_response(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        detail = response.json()
    except ValueError:
        detail = response.text
    raise RuntimeError(f"Alpha returned HTTP {response.status_code}: {detail}")


async def _run(args: argparse.Namespace) -> int:
    base_url = _base_url(args.base_url)
    async with httpx.AsyncClient(
        base_url=base_url, timeout=httpx.Timeout(10.0)
    ) as client:
        if args.headless_local_token:
            admin_token = _mint_admin_token(profile_id=args.profile_id)
        else:
            pin = _pin(args.pin)
            admin_token = await _admin_token(
                client, pin=pin, profile_id=args.profile_id
            )
        pending = await _pending(client, admin_token=admin_token)

        if args.command == "pending":
            items = [
                item
                for item in pending
                if not args.financial_only or _is_financial_paper(item)
            ]
            print(
                json.dumps(
                    {"pending": items, "count": len(items)}, indent=2, default=str
                )
            )
            return 0

        selected = _select_pending(
            pending,
            approval_id=args.approval_id,
            latest_financial_paper=args.latest_financial_paper,
        )
        if args.headless_local_token:
            approval_token = _mint_approval_token(profile_id=args.profile_id)
        else:
            approval_token = await _approval_token(client, pin=pin)
        decision: Literal["approved", "denied"] = (
            "approved" if args.command == "approve" else "denied"
        )
        result = await _decide(
            client,
            admin_token=admin_token,
            approval_token=approval_token,
            queue_id=str(selected["id"]),
            decision=decision,
        )
        print(
            json.dumps(
                {
                    "decision": decision,
                    "queue_id": result.get("queue_id"),
                    "description": result.get("description"),
                    "expires_at": result.get("expires_at"),
                },
                indent=2,
                default=str,
            )
        )
        return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="financial_approval_operator")
    parser.add_argument("--base-url")
    parser.add_argument(
        "--pin", help="approval PIN; prefer ALPHA_PIN or interactive prompt"
    )
    parser.add_argument("--profile-id", default="ken")
    parser.add_argument(
        "--headless-local-token",
        action="store_true",
        help="mint short-lived local JWTs from ALPHA_JWT_PRIVATE_KEY instead of PIN auth",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    pending = sub.add_parser("pending", help="list pending Alpha approvals")
    pending.add_argument("--financial-only", action="store_true")

    for command in ("approve", "deny"):
        decide = sub.add_parser(command, help=f"{command} a pending approval")
        decide.add_argument("--approval-id")
        decide.add_argument("--latest-financial-paper", action="store_true")

    return parser


def main() -> int:
    try:
        import asyncio

        return asyncio.run(_run(_parser().parse_args()))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
