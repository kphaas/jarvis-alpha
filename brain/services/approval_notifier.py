"""
Approval notification service.

Generates rich context for T4/T5 approval requests and delivers them.
Phase 2: log + buddy event
Phase 3: add Pushover / mobile push

Gateway is sole internet egress — when Pushover is added, Brain will
POST to Gateway which forwards to Pushover API.
"""

import json
from brain.db.pool import get_pool
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

# Risk context templates — explain WHY this tier matters
TIER_CONTEXT = {
    "T4": "This action may affect system behavior or child-facing content. It requires your approval before execution.",
    "T5": "This is a high-risk action — it may be destructive, modify admin settings, or be irreversible. It was blocked and requires your explicit approval.",
}

# Action class descriptions — human-readable risk explanations
ACTION_CONTEXT = {
    "destructive": "Permanently deletes data. Cannot be undone.",
    "admin": "Changes system configuration, user permissions, or security settings.",
    "deploy": "Deploys code or configuration changes to a live node.",
    "child_facing": "Affects content or settings visible to Ryleigh or Sloane. Extra caution required.",
    "unclassified": "This route has no security classification. Blocked by default until classified.",
}


def build_notification(
    queue_id: str,
    tier: str,
    action_classes: list[str],
    method: str,
    path: str,
    actor_sub: str,
    actor_type: str,
    overnight: bool = False,
) -> dict:
    """Build a rich notification payload for a T4/T5 approval request.

    Returns dict with 'title', 'body', 'priority', and 'payload' fields.
    """
    tier_desc = TIER_CONTEXT.get(tier, "This action requires approval.")

    risk_lines = []
    for ac in action_classes:
        desc = ACTION_CONTEXT.get(ac)
        if desc:
            risk_lines.append(f"  {ac}: {desc}")

    risk_detail = (
        "\n".join(risk_lines) if risk_lines else "  No specific risk context available."
    )

    if_approved = "The original request will be retryable for 10 minutes."
    if_denied = (
        "The request will be permanently denied. The caller will need to re-submit."
    )

    time_context = (
        "Queued overnight — will appear in morning approval panel."
        if overnight
        else "Queued now — waiting for your decision."
    )

    title = f"JARVIS Approval Required — {tier}"

    body = f"""{tier} · {", ".join(action_classes)}
{method} {path}

Requested by: {actor_sub} ({actor_type})
Queue ID: {queue_id}

Why this needs approval:
{tier_desc}

Risk detail:
{risk_detail}

If approved:
  {if_approved}

If denied:
  {if_denied}

{time_context}"""

    priority = 2 if tier == "T5" else 1

    return {
        "title": title,
        "body": body,
        "priority": priority,
        "payload": {
            "queue_id": queue_id,
            "tier": tier,
            "action_classes": action_classes,
            "method": method,
            "path": path,
            "actor_sub": actor_sub,
            "actor_type": actor_type,
            "overnight": overnight,
        },
    }


async def send_approval_notification(
    queue_id: str,
    tier: str,
    action_classes: list[str],
    method: str,
    path: str,
    actor_sub: str,
    actor_type: str,
    overnight: bool = False,
) -> bool:
    """Send approval notification. Currently logs + writes buddy event.

    Phase 3: add Pushover via Gateway.
    Returns True if notification was delivered.
    """
    notif = build_notification(
        queue_id=queue_id,
        tier=tier,
        action_classes=action_classes,
        method=method,
        path=path,
        actor_sub=actor_sub,
        actor_type=actor_type,
        overnight=overnight,
    )

    logger.warning("APPROVAL_NOTIFY: %s", notif["title"])
    logger.info("APPROVAL_NOTIFY_BODY:\n%s", notif["body"])

    # Write buddy event so it shows in the UI
    pool = get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.fetchval(
                    "SELECT public.record_buddy_event($1, $2, $3, $4, $5, $6, $7)",
                    "system",
                    "alert",
                    notif["title"],
                    notif["body"],
                    notif["priority"],
                    "approval_gateway",
                    json.dumps(notif["payload"]),
                )
        except Exception:
            logger.error("Failed to write approval buddy event", exc_info=True)
            return False

    # Phase 3: POST to Gateway /v1/notify/pushover
    # url = f"{GATEWAY_URL}/v1/notify/pushover"
    # await async_post(url, json=notif)

    return True
