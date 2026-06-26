"""Approval queue helpers for Beacon browser-use requests."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

import asyncpg

from brain.services.internet_scout.models import (
    InternetScoutBrowserApprovalPreview,
    InternetScoutRequest,
    InternetTool,
    PolicyDecision,
)
from brain.services.internet_scout.safety import validate_url

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


def browser_task_approval_preview(
    request: InternetScoutRequest,
    decision: PolicyDecision,
) -> InternetScoutBrowserApprovalPreview:
    """Build a browser-action preview without raw query or full URL text."""

    parameters_hash = browser_task_parameters_hash(request, decision)
    allowed_hosts, url_hashes = _browser_review_targets(request.urls)
    return InternetScoutBrowserApprovalPreview(
        selected_tool=decision.tool,
        risk_tier=decision.tier,
        sensitivity=request.sensitivity,
        has_query=bool(request.query),
        url_count=len(request.urls),
        max_pages=request.max_pages,
        max_depth=request.max_depth,
        needs_interaction=request.needs_interaction,
        allowed_hosts=allowed_hosts,
        url_hashes=url_hashes,
        screenshot_policy={
            "before_navigation_required": False,
            "after_observation_required": True,
            "screenshots_available_after_run": True,
            "screenshot_refs_redacted_until_execution": True,
        },
        risk_labels=_browser_risk_labels(
            request=request,
            decision=decision,
            allowed_hosts=allowed_hosts,
        ),
        action_timeline=_browser_action_timeline(allowed_hosts=allowed_hosts),
        approval_hash_prefix=parameters_hash[:12],
    )


def _browser_review_targets(urls: list[str]) -> tuple[list[str], list[str]]:
    hosts: list[str] = []
    url_hashes: list[str] = []
    for url in urls:
        safety = validate_url(url)
        if safety.host and safety.host not in hosts:
            hosts.append(safety.host)
        url_hashes.append("sha256:" + hashlib.sha256(url.encode("utf-8")).hexdigest())
    return hosts, url_hashes


def _browser_risk_labels(
    *,
    request: InternetScoutRequest,
    decision: PolicyDecision,
    allowed_hosts: list[str],
) -> list[str]:
    labels = [
        "human_approval_required",
        "public_web_only",
        "same_host_only",
        "screenshots_required",
        "no_downloads",
        "no_forms",
        "no_credentials",
        "raw_web_content_untrusted",
    ]
    if request.sensitivity != "normal":
        labels.append(f"sensitivity_{request.sensitivity}")
    if decision.tier in {"T4", "T5"}:
        labels.append(f"risk_{decision.tier.lower()}")
    if not allowed_hosts:
        labels.append("host_allowlist_missing")
    return labels


def _browser_action_timeline(*, allowed_hosts: list[str]) -> list[dict[str, object]]:
    host_count = len(allowed_hosts)
    return [
        {
            "step": "review_request",
            "status": "pending_operator_review",
            "description": "Review redacted task shape, risk tier, host allowlist, and screenshot policy.",
        },
        {
            "step": "approve_or_deny",
            "status": "operator_required",
            "description": "Approval unlock is required before any browser runtime starts.",
        },
        {
            "step": "sandbox",
            "status": "planned",
            "description": "Create a public-web-only sandbox with downloads, forms, credentials, and cross-host navigation disabled.",
            "allowed_host_count": host_count,
        },
        {
            "step": "navigate",
            "status": "planned",
            "description": "Navigate only to the reviewed host allowlist; full URLs stay hashed in the approval payload.",
        },
        {
            "step": "inspect_controls",
            "status": "planned",
            "description": "Block forms, credentials, payment, login, and other disallowed controls before extraction.",
        },
        {
            "step": "screenshot",
            "status": "planned",
            "description": "Capture review screenshots after observation; screenshot refs are recorded in the audit event.",
        },
        {
            "step": "extract_text",
            "status": "planned",
            "description": "Extract sanitized visible text as untrusted evidence only.",
        },
    ]
