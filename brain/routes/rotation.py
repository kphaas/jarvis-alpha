"""Keyturner rotation routes."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Body, HTTPException

from brain.db.pool import get_pool
from brain.db.rls import platform_admin_connection
from brain.services.key_rotation import (
    KEY_FORMAT_RULES,
    RotateRequest,
    RotateResponse,
    validate_key_format,
)
from brain.skills.handlers import build_skill_runner
from brain.skills.policy_gate import SkillInvocation

rotation_router = APIRouter(prefix="/v1/security", tags=["security"])


def _rotation_id(key_name: str, new_value: str) -> str:
    digest = hashlib.sha256(f"{key_name}\0{new_value}".encode("utf-8")).hexdigest()
    return f"keyturner-{key_name.lower()}-{digest[:16]}"


@rotation_router.get("/rotatable-keys")
async def rotatable_keys():
    """Return list of keys that can be rotated, with format rules."""
    return {
        "keys": [
            {
                "key_name": key_name,
                "provider": rule["provider"],
                "prefix": rule["prefix"],
                "min_length": rule["min_length"],
            }
            for key_name, rule in KEY_FORMAT_RULES.items()
        ]
    }


@rotation_router.post("/rotate-key", response_model=RotateResponse)
async def rotate_key(req: RotateRequest = Body(...)):
    """Queue or execute a Keyturner rotation through SkillRunner approval."""

    validate_key_format(req.key_name, req.new_value)
    rotation_id = req.rotation_id or _rotation_id(req.key_name, req.new_value)
    runner = build_skill_runner()
    pool = get_pool()

    async with platform_admin_connection(
        source="http", audit_actor=f"keyturner:{req.key_name}", pool=pool
    ) as conn:
        result = await runner.run(
            conn,
            SkillInvocation(
                agent_id="keyturner",
                skill_name="secrets.rotate",
                idempotency_key=rotation_id,
            ),
            payload={
                "key_name": req.key_name,
                "new_value": req.new_value,
                "rotation_id": rotation_id,
            },
        )

    if result.requires_approval:
        return RotateResponse(
            status="approval_required",
            rotation_id=rotation_id,
            key_name=req.key_name,
            error="Approval required. Approve the queued Keyturner request, then retry this rotation.",
            approval_queue_id=result.approval_queue_id,
            approval_status=result.approval_status,
        )
    if result.denied:
        raise HTTPException(status_code=403, detail=result.decision.reason)

    try:
        output = dict(result.output or {})
        return RotateResponse(
            status=str(output.get("status", "unknown")),
            rotation_id=str(output.get("rotation_id") or rotation_id),
            key_name=str(output.get("key_name") or req.key_name),
            error=output.get("error"),
            old_key_health=output.get("old_key_health"),
            new_key_health=output.get("new_key_health"),
            approval_queue_id=result.approval_queue_id,
            approval_status=result.approval_status,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Invalid Keyturner result") from exc
