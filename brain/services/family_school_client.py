from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class FamilySchoolEmailRule:
    id: str
    child_member_id: str
    child_name: str
    label: str
    sender_email: str
    rule_type: str


class FamilySchoolClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url
            or os.environ.get("JARVIS_FAMILY_API_URL")
            or "https://127.0.0.1:8187"
        ).rstrip("/")

    def _token(self, scopes: list[str]) -> str:
        import jwt

        key_path = Path.home() / "jarvis" / "pki" / "services" / "brain_private.pem"
        private_key = key_path.read_text()
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": "alpha-school-email",
            "iss": "brain",
            "actor_type": "service",
            "scopes": scopes,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + 3600,
        }
        family_id = os.environ.get("JARVIS_FAMILY_ID", "").strip()
        if family_id:
            claims["family_id"] = family_id
        return jwt.encode(
            claims,
            private_key,
            algorithm="RS256",
        )

    async def active_rules(self) -> list[FamilySchoolEmailRule]:
        token = self._token(["family.school_email.read"])
        async with httpx.AsyncClient(timeout=20, verify=False) as client:
            response = await client.get(
                f"{self.base_url}/v1/school-email/rules/export",
                headers={"Authorization": f"Bearer {token}"},
            )
        response.raise_for_status()
        return [
            FamilySchoolEmailRule(
                id=str(row["id"]),
                child_member_id=str(row["child_member_id"]),
                child_name=str(row.get("child_name") or ""),
                label=str(row.get("label") or ""),
                sender_email=str(row["sender_email"]),
                rule_type=str(row.get("rule_type") or "teacher"),
            )
            for row in response.json().get("rules", [])
        ]

    async def import_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post_import("event", payload)

    async def import_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post_import("action", payload)

    async def _post_import(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = self._token(["family.school_email.import"])
        async with httpx.AsyncClient(timeout=20, verify=False) as client:
            response = await client.post(
                f"{self.base_url}/v1/school-email/imports/{kind}",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
        response.raise_for_status()
        return response.json()
