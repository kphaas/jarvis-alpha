"""Shared Keyturner rotation service."""

from __future__ import annotations

import asyncio
import json
import subprocess

from fastapi import HTTPException
from pydantic import BaseModel

from brain.config.node_addresses import GATEWAY_URL
from brain.db.pool import get_pool
from brain.db.rls import platform_admin_connection
from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_brain")

KEY_FORMAT_RULES: dict[str, dict] = {
    "ANTHROPIC_API_KEY": {
        "prefix": "sk-ant-",
        "min_length": 40,
        "provider": "Anthropic (Claude)",
    },
    "GEMINI_API_KEY": {
        "prefix": "AIza",
        "min_length": 30,
        "provider": "Google (Gemini)",
    },
    "PERPLEXITY_API_KEY": {
        "prefix": "pplx-",
        "min_length": 40,
        "provider": "Perplexity",
    },
}


class RotateRequest(BaseModel):
    key_name: str
    new_value: str
    rotation_id: str | None = None


class RotateResponse(BaseModel):
    status: str
    rotation_id: str
    key_name: str
    error: str | None = None
    old_key_health: str | None = None
    new_key_health: str | None = None
    approval_queue_id: str | None = None
    approval_status: str | None = None


def validate_key_format(key_name: str, new_value: str) -> None:
    if key_name not in KEY_FORMAT_RULES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown key: {key_name}. Allowed: {sorted(KEY_FORMAT_RULES.keys())}",
        )

    rule = KEY_FORMAT_RULES[key_name]
    if rule.get("prefix") and not new_value.startswith(rule["prefix"]):
        raise HTTPException(
            status_code=400,
            detail=f"Key must start with '{rule['prefix']}'",
        )
    if rule.get("min_length") and len(new_value) < rule["min_length"]:
        raise HTTPException(
            status_code=400,
            detail=f"Key must be at least {rule['min_length']} characters",
        )
    if not new_value.isascii():
        raise HTTPException(status_code=400, detail="Key must be ASCII only")


async def rotate_key_via_gateway(req: RotateRequest) -> RotateResponse:
    """Forward an approved rotation to Gateway and audit the result."""

    validate_key_format(req.key_name, req.new_value)
    if not req.rotation_id:
        raise HTTPException(status_code=400, detail="rotation_id is required")
    gateway_token = get_secret("GATEWAY_TOKEN")
    gateway_url = f"{GATEWAY_URL.rstrip('/')}/v1/admin/rotate-key"
    payload = json.dumps(
        {
            "key_name": req.key_name,
            "new_value": req.new_value,
            "rotation_id": req.rotation_id,
        }
    )

    cmd = [
        "curl",
        "-sk",
        "--max-time",
        "45",
        gateway_url,
        "-X",
        "POST",
        "-H",
        "Content-Type: application/json",
        "-H",
        f"Authorization: Bearer {gateway_token}",
        "-d",
        payload,
    ]

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=50
        )
        if result.returncode != 0:
            raise HTTPException(status_code=502, detail="Gateway unreachable")

        data = json.loads(result.stdout)
        pool = get_pool()
        async with platform_admin_connection(
            source="http", audit_actor=f"keyturner:{req.key_name}", pool=pool
        ) as conn:
            await conn.execute(
                """INSERT INTO secret_access_log (key_name, source, accessed_at, node)
                   VALUES ($1, $2, now(), $3)""",
                req.key_name,
                f"rotation_{data.get('status', 'unknown')}",
                "gateway",
            )

        return RotateResponse(
            status=data.get("status", "unknown"),
            rotation_id=data.get("rotation_id", req.rotation_id),
            key_name=req.key_name,
            error=data.get("error"),
            old_key_health=data.get("old_key_health"),
            new_key_health=data.get("new_key_health"),
        )
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Gateway returned invalid JSON")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("rotation_proxy_error key=%s error=%s", req.key_name, exc)
        raise HTTPException(status_code=500, detail="Rotation failed")
