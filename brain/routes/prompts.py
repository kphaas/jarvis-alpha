from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from brain.db.pool import get_pool

router = APIRouter(prefix="/v1/prompts", tags=["prompts"])


def _serialize_prompt_row(row: Any, include_system_prompt: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["id"],
        "prompt_id": row["prompt_id"],
        "version": int(row["version"]),
        "model_hint": row["model_hint"],
        "scope": row["scope"],
        "is_active": bool(row["is_active"]),
        "created_at": (
            row["created_at"].isoformat()
            if isinstance(row["created_at"], datetime)
            else row["created_at"]
        ),
    }
    if include_system_prompt:
        out["system_prompt"] = row["system_prompt"]
    return out


@router.get("/")
async def list_active_prompts():
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT prompt_id, version, model_hint, scope, created_at
            FROM alpha_prompt_registry
            WHERE is_active = true
            ORDER BY prompt_id ASC, version DESC
            """
        )

    payload = [
        {
            "prompt_id": row["prompt_id"],
            "version": int(row["version"]),
            "model_hint": row["model_hint"],
            "scope": row["scope"],
            "created_at": (
                row["created_at"].isoformat()
                if isinstance(row["created_at"], datetime)
                else row["created_at"]
            ),
        }
        for row in rows
    ]
    return JSONResponse(content=payload)


@router.get("/{prompt_id}")
async def get_prompt(prompt_id: str, v: int | None = None):
    pool = get_pool()
    async with pool.acquire() as conn:
        if v is not None:
            row = await conn.fetchrow(
                """
                SELECT id, prompt_id, version, system_prompt, model_hint, scope, is_active, created_at
                FROM alpha_prompt_registry
                WHERE prompt_id = $1 AND version = $2
                LIMIT 1
                """,
                prompt_id,
                v,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT id, prompt_id, version, system_prompt, model_hint, scope, is_active, created_at
                FROM alpha_prompt_registry
                WHERE prompt_id = $1 AND is_active = true
                ORDER BY version DESC
                LIMIT 1
                """,
                prompt_id,
            )

    if not row:
        raise HTTPException(status_code=404, detail="prompt not found")

    return JSONResponse(content=_serialize_prompt_row(row, include_system_prompt=True))


@router.post("/")
async def create_prompt(request: Request):
    body = await request.json()
    prompt_id = body.get("prompt_id")
    system_prompt = body.get("system_prompt")
    model_hint = body.get("model_hint")
    scope = body.get("scope")

    if not isinstance(prompt_id, str) or not prompt_id.strip():
        raise HTTPException(status_code=400, detail="prompt_id is required")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise HTTPException(status_code=400, detail="system_prompt is required")
    if scope not in {"alpha", "forge", "global"}:
        raise HTTPException(
            status_code=400, detail="scope must be alpha, forge, or global"
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            next_version = await conn.fetchval(
                """
                SELECT COALESCE(MAX(version), 0) + 1
                FROM alpha_prompt_registry
                WHERE prompt_id = $1
                """,
                prompt_id,
            )

            await conn.execute(
                """
                UPDATE alpha_prompt_registry
                SET is_active = false
                WHERE prompt_id = $1
                """,
                prompt_id,
            )

            row = await conn.fetchrow(
                """
                INSERT INTO alpha_prompt_registry (
                    prompt_id,
                    version,
                    system_prompt,
                    model_hint,
                    scope,
                    is_active
                )
                VALUES ($1, $2, $3, $4, $5, true)
                RETURNING id, prompt_id, version, system_prompt, model_hint, scope, is_active, created_at
                """,
                prompt_id,
                int(next_version),
                system_prompt,
                model_hint,
                scope,
            )

    return JSONResponse(content=_serialize_prompt_row(row, include_system_prompt=True))
