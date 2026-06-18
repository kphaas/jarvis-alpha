"""Approval queue helpers for Beacon browser-use requests."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

import asyncpg

from brain.services.internet_scout.models import (
    InternetScoutRequest,
    InternetTool,
    PolicyDecision,
)

BROWSER_TASK_APPROVAL_ACTION_CLASSES = (
    "beacon_browser_use",
    "external_call",
    "security_write",
)


class BrowserApprovalError(RuntimeError):
    """Raised when a Beacon browser-use approval cannot be queued safely."""


async def enqueue_browser_task_approval(
    conn: asyncpg.Connection,
    *,
    request: InternetScoutRequest,
    decision: PolicyDecision,
    actor_sub: str,
    actor_type: str,
    nonce: str,
) -> UUID:
    """Queue browser-use work for human review without storing raw task text."""

    if decision.tool != InternetTool.BROWSER_USE or not decision.requires_approval:
        raise BrowserApprovalError("browser-use approval requires a browser policy")

    parameters_hash = browser_task_parameters_hash(request, decision)
    description = browser_task_approval_description(request, decision)
    try:
        async with conn.transaction():
            queue_id = await conn.fetchval(
                """
                SELECT public.enqueue_approval_request(
                    $1::text[], $2, $3, $4, $5, $6, $7
                )
                """,
                list(BROWSER_TASK_APPROVAL_ACTION_CLASSES),
                decision.tier,
                actor_sub,
                actor_type,
                description,
                parameters_hash,
                nonce,
            )
    except asyncpg.UniqueViolationError:
        existing_id = await conn.fetchval(
            """
            SELECT id
            FROM public.alpha_approval_queue
            WHERE actor_sub = $1
              AND parameters_hash = $2
              AND status = 'pending'
              AND expires_at > NOW()
            ORDER BY requested_at DESC
            LIMIT 1
            """,
            actor_sub,
            parameters_hash,
        )
        if existing_id is None:
            raise
        return existing_id

    if queue_id is None:
        raise BrowserApprovalError("enqueue_approval_request returned no queue id")
    return queue_id


async def require_approved_browser_task(
    conn: asyncpg.Connection,
    *,
    approval_queue_id: UUID,
    actor_sub: str,
    parameters_hash: str,
) -> None:
    """Verify an approved, unexpired queue row for this exact browser task."""

    row = await conn.fetchrow(
        """
        SELECT id
        FROM public.alpha_approval_queue
        WHERE id = $1
          AND actor_sub = $2
          AND parameters_hash = $3
          AND status = 'approved'
          AND expires_at > NOW()
        LIMIT 1
        """,
        approval_queue_id,
        actor_sub,
        parameters_hash,
    )
    if row is None:
        raise BrowserApprovalError("browser_task_approval_not_found")


async def consume_browser_task_approval(
    conn: asyncpg.Connection,
    *,
    approval_queue_id: UUID,
) -> None:
    """Mark an approved browser task queue row executed after successful run."""

    await conn.execute(
        "SELECT public.consume_approved_queue_item($1::uuid)",
        approval_queue_id,
    )


def browser_task_parameters_hash(
    request: InternetScoutRequest,
    decision: PolicyDecision,
) -> str:
    payload = {
        "approval_contract_version": 1,
        "request": request.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def browser_task_approval_description(
    request: InternetScoutRequest,
    decision: PolicyDecision,
) -> str:
    query_state = "query=yes" if request.query else "query=no"
    return (
        "Beacon browser-use approval "
        f"({decision.tier}, {query_state}, urls={len(request.urls)}, "
        f"sensitivity={request.sensitivity})"
    )
