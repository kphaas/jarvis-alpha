"""Mattermost ChatOps command endpoint.

ChatOps is token-authenticated and keeps state-changing Agent Board commands on
the same audited queue/status paths used by Helm.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException
from pydantic import BaseModel

from brain.config.secrets import get_secret
from brain.db.rls import platform_admin_connection
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/chatops", tags=["chatops"])

BOARD_ROLES = {"general", "research", "code", "review", "deploy", "monitor"}
BOARD_NEEDS_ME_STATUSES = ("needs_approval", "blocked", "handoff_ready")


class MattermostCommandResponse(BaseModel):
    response_type: str = "ephemeral"
    text: str


@dataclass(frozen=True, slots=True)
class AlphaCommand:
    name: str
    args: tuple[str, ...] = ()


def _check_mattermost_token(token: str) -> None:
    try:
        expected = get_secret("MATTERMOST_COMMAND_TOKEN").strip()
    except KeyError as exc:
        logger.error("mattermost_command missing_token")
        raise HTTPException(
            status_code=503,
            detail="Mattermost commands are not configured",
        ) from exc

    if not expected or not hmac.compare_digest(token, expected):
        logger.warning("mattermost_command bad_token")
        raise HTTPException(status_code=403, detail="Invalid Mattermost token")


def parse_alpha_command(text: str | None) -> AlphaCommand:
    parts = (text or "help").strip().split()
    if not parts:
        return AlphaCommand(name="help")
    return AlphaCommand(name=parts[0].lower(), args=tuple(parts[1:]))


@router.post("/mattermost/command", response_model=MattermostCommandResponse)
async def mattermost_command(
    token: str = Form(...),
    text: str = Form(default="help"),
    user_name: str = Form(default="unknown"),
) -> MattermostCommandResponse:
    _check_mattermost_token(token)
    command = parse_alpha_command(text)
    audit_actor = f"mattermost:{user_name or 'unknown'}"

    try:
        async with platform_admin_connection(
            source="http",
            audit_actor=audit_actor,
        ) as conn:
            if command.name in {"help", ""}:
                body = _help_text()
            elif command.name == "health":
                body = await _health_text(conn)
            elif command.name == "agents":
                body = await _agents_text(conn)
            elif command.name == "network":
                body = await _network_text(conn)
            elif command.name == "approvals":
                body = await _approvals_text(conn)
            elif command.name in {"dreams", "dream"}:
                body = await _dreams_text(conn, command.args)
            elif command.name in {"board", "agent-board"}:
                body = await _board_text(conn, command.args, audit_actor)
            else:
                body = _unknown_text(command.name)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "mattermost_command failed command=%s", command.name, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Command failed") from exc

    logger.info("mattermost_command ok user=%s command=%s", user_name, command.name)
    return MattermostCommandResponse(text=body)


def _help_text() -> str:
    return "\n".join(
        [
            "**Alpha commands**",
            "`/alpha health` - Brain, Temporal, and Dream worker status",
            "`/alpha agents` - agent registry summary",
            "`/alpha network` - read-only Sweep summary",
            "`/alpha approvals` - pending approval queue",
            "`/alpha dreams [n]` - recent Dream sessions",
            "`/alpha board` - Agent Board status summary",
            "`/alpha board blocked` - blocked work items",
            "`/alpha board needs-me` - approval, blocked, and handoff-ready items",
            "`/alpha board queue <role> <title>` - queue an Agent Board item",
            "`/alpha board approve-handoff <id>` - mark a handoff-ready item done",
        ]
    )


def _unknown_text(name: str) -> str:
    return f"Unknown Alpha command `{name}`.\n\n{_help_text()}"


async def _health_text(conn) -> str:
    counts = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'running') AS running_dreams,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_dreams,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed_dreams
        FROM public.alpha_dream_sessions
        """
    )
    pending_approvals = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM public.alpha_approval_queue
        WHERE status = 'pending'
          AND expires_at > NOW()
        """
    )
    enabled_agents = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM public.alpha_agents
        WHERE status = 'active'
          AND enabled = true
        """
    )
    return "\n".join(
        [
            "**Alpha Health**",
            f"Active agents: `{enabled_agents or 0}`",
            f"Pending approvals: `{pending_approvals or 0}`",
            (
                "Dream sessions: "
                f"`{counts['running_dreams'] or 0}` running, "
                f"`{counts['pending_dreams'] or 0}` pending, "
                f"`{counts['failed_dreams'] or 0}` failed"
            ),
        ]
    )


async def _agents_text(conn) -> str:
    rows = await conn.fetch(
        """
        SELECT agent_id, display_name, status, enabled, risk_tier, cadence, metadata
        FROM public.alpha_agents
        ORDER BY status ASC, enabled DESC, agent_id ASC
        LIMIT 20
        """
    )
    lines = ["**Alpha Agents**"]
    for row in rows:
        enabled = "on" if row["enabled"] else "off"
        lines.append(
            f"- `{row['agent_id']}` {enabled} · {row['status']} · "
            f"{row['risk_tier']} · {row['cadence'] or 'manual'}"
        )
    return "\n".join(lines)


async def _network_text(conn) -> str:
    agent = await conn.fetchrow(
        """
        SELECT agent_id, display_name, status, enabled, cadence, metadata
        FROM public.alpha_agents
        WHERE agent_id = 'sweep'
        """
    )
    if not agent:
        return "**Alpha Network**\nSweep is not registered."

    last_run = await conn.fetchrow(
        """
        SELECT status, trigger_type, started_at, completed_at, error_text, created_at
        FROM public.alpha_agent_runs
        WHERE agent_id = 'sweep'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    events = await conn.fetch(
        """
        SELECT event_type, severity, title, notification_status, created_at
        FROM public.alpha_agent_events
        WHERE agent_id = 'sweep'
        ORDER BY created_at DESC
        LIMIT 3
        """
    )

    metadata = _jsonb(agent["metadata"])
    enabled = "on" if agent["enabled"] else "off"
    lines = [
        "**Alpha Network**",
        (
            f"Sweep: `{enabled}` · `{agent['status']}` · "
            f"cadence `{agent['cadence'] or 'manual'}`"
        ),
        (
            "Last observed: "
            f"WAN `{metadata.get('last_wan_status', 'unknown')}` · "
            f"health `{metadata.get('last_health_status', 'unknown')}` · "
            f"client baseline `{len(metadata.get('last_client_keys') or [])}`"
        ),
    ]
    if last_run:
        completed_at = last_run["completed_at"] or last_run["created_at"]
        lines.append(
            "Last run: "
            f"`{last_run['status']}` via `{last_run['trigger_type']}` "
            f"at `{completed_at.isoformat() if completed_at else 'unknown'}`"
        )
        if last_run["error_text"]:
            lines.append("Last run error: redacted; check Alpha logs.")
    else:
        lines.append("Last run: `none`")

    if events:
        lines.append("Recent network events:")
        for event in events:
            lines.append(
                f"- `{event['severity']}` `{event['event_type']}` "
                f"{event['title']} ({event['notification_status']})"
            )
    else:
        lines.append("Recent network events: none")

    return "\n".join(lines)


async def _approvals_text(conn) -> str:
    rows = await conn.fetch(
        """
        SELECT id, risk_tier, description, requested_at, expires_at
        FROM public.alpha_approval_queue
        WHERE status = 'pending'
          AND expires_at > NOW()
        ORDER BY requested_at ASC
        LIMIT 5
        """
    )
    if not rows:
        return "**Alpha Approvals**\nNo pending approvals."

    lines = ["**Alpha Approvals**"]
    for row in rows:
        lines.append(
            f"- `{row['risk_tier']}` `{row['id']}` {row['description']} "
            f"(expires {row['expires_at'].isoformat()})"
        )
    return "\n".join(lines)


async def _dreams_text(conn, args: tuple[str, ...]) -> str:
    limit = _bounded_limit(args, default=5, maximum=10)
    rows = await conn.fetch(
        """
        SELECT id, status, trigger, goal_type, step_count, steps_completed,
               steps_failed, steps_blocked, cost_actual_usd, created_at
        FROM public.alpha_dream_sessions
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit,
    )
    if not rows:
        return "**Alpha Dreams**\nNo Dream sessions found."

    lines = [f"**Alpha Dreams** last `{limit}`"]
    for row in rows:
        lines.append(
            f"- `#{row['id']}` {row['status']} · {row['goal_type']} · "
            f"{row['steps_completed']}/{row['step_count']} complete · "
            f"failed `{row['steps_failed']}` blocked `{row['steps_blocked']}` · "
            f"${float(row['cost_actual_usd'] or 0):.2f}"
        )
    return "\n".join(lines)


async def _board_text(conn, args: tuple[str, ...], actor: str) -> str:
    if not args or args[0] in {"status", "summary"}:
        return await _board_summary_text(conn)
    subcommand = args[0].lower()
    if subcommand == "blocked":
        return await _board_list_text(conn, statuses=("blocked",), title="Blocked")
    if subcommand in {"needs-me", "mine"}:
        return await _board_list_text(
            conn,
            statuses=BOARD_NEEDS_ME_STATUSES,
            title="Needs Operator",
        )
    if subcommand == "queue":
        return await _board_queue_text(conn, args[1:], actor)
    if subcommand in {"approve-handoff", "handoff-done"}:
        return await _board_approve_handoff_text(conn, args[1:], actor)
    return (
        f"Unknown board command `{subcommand}`.\n"
        "Try `/alpha board`, `/alpha board blocked`, "
        "`/alpha board needs-me`, `/alpha board queue <role> <title>`, "
        "or `/alpha board approve-handoff <id>`."
    )


async def _board_summary_text(conn) -> str:
    rows = await conn.fetch(
        """
        SELECT status, COUNT(*) AS count
          FROM public.alpha_agent_work_items
         WHERE status != 'cancelled'
         GROUP BY status
        """
    )
    counts = {row["status"]: int(row["count"] or 0) for row in rows}
    ordered_statuses = [
        "queued",
        "in_progress",
        "blocked",
        "needs_approval",
        "handoff_ready",
        "done",
    ]
    lines = ["**Alpha Agent Board**"]
    lines.extend(
        f"- `{status}`: `{counts.get(status, 0)}`" for status in ordered_statuses
    )
    return "\n".join(lines)


async def _board_list_text(
    conn,
    *,
    statuses: tuple[str, ...],
    title: str,
) -> str:
    rows = await conn.fetch(
        """
        SELECT id, title, role, status, priority, blocked_reason, updated_at
          FROM public.alpha_agent_work_items
         WHERE status = ANY($1::text[])
         ORDER BY priority DESC, updated_at ASC
         LIMIT 8
        """,
        list(statuses),
    )
    if not rows:
        return f"**Alpha Agent Board: {title}**\nNo matching work items."

    lines = [f"**Alpha Agent Board: {title}**"]
    for row in rows:
        reason = f" - {row['blocked_reason']}" if row["blocked_reason"] else ""
        lines.append(
            f"- `{row['status']}` `{row['id']}` {row['title']} "
            f"({row['role']}, p{row['priority']}){reason}"
        )
    return "\n".join(lines)


async def _board_queue_text(conn, args: tuple[str, ...], actor: str) -> str:
    if len(args) < 2:
        return "Usage: `/alpha board queue <role> <title>`"
    role = args[0].lower()
    if role not in BOARD_ROLES:
        roles = "`, `".join(sorted(BOARD_ROLES))
        return f"Invalid role `{role}`. Use one of `{roles}`."
    title = " ".join(args[1:]).strip()
    if not title:
        return "Usage: `/alpha board queue <role> <title>`"

    async with conn.transaction():
        row = await conn.fetchrow(
            """
            INSERT INTO public.alpha_agent_work_items (
                workspace_id, title, description, source_surface, requested_by,
                role, priority, required_skills, approval_tier,
                acceptance_criteria, metadata
            )
            VALUES (
                'personal', $1, '', 'chatops', $2,
                $3, 5, ARRAY[]::text[], 'T1',
                $4::jsonb, $5::jsonb
            )
            RETURNING id, title, role, status
            """,
            title[:180],
            actor,
            role,
            json.dumps(["Operator queued from Mattermost ChatOps."]),
            json.dumps({"chatops": {"command": "board queue", "actor": actor}}),
        )
        if row is None:
            raise HTTPException(status_code=500, detail="Work item insert failed")
        await conn.execute(
            """
            INSERT INTO public.alpha_agent_work_item_events (
                work_item_id, event_type, actor, to_status, message, metadata
            )
            VALUES ($1, 'created', $2, 'queued', $3, $4::jsonb)
            """,
            row["id"],
            actor,
            "work item queued from ChatOps",
            json.dumps({"source_surface": "chatops", "role": role}),
        )
    logger.info("mattermost_board_queue ok work_item_id=%s role=%s", row["id"], role)
    return (
        "**Alpha Agent Board**\n"
        f"Queued `{row['id']}` as `{row['role']}`: {row['title']}"
    )


async def _board_approve_handoff_text(conn, args: tuple[str, ...], actor: str) -> str:
    if len(args) != 1:
        return "Usage: `/alpha board approve-handoff <work_item_id>`"
    try:
        work_item_id = UUID(args[0])
    except ValueError:
        return f"Invalid work item id `{args[0]}`."

    async with conn.transaction():
        current = await conn.fetchrow(
            """
            SELECT id, title, status
              FROM public.alpha_agent_work_items
             WHERE id = $1
             FOR UPDATE
            """,
            work_item_id,
        )
        if current is None:
            return f"Work item `{work_item_id}` was not found."
        if current["status"] != "handoff_ready":
            return (
                f"Work item `{work_item_id}` is `{current['status']}`, "
                "not `handoff_ready`."
            )

        metadata = {"chatops": {"command": "board approve-handoff", "actor": actor}}
        updated = await conn.fetchrow(
            """
            UPDATE public.alpha_agent_work_items
               SET status = 'done',
                   completed_at = NOW(),
                   metadata = metadata || $2::jsonb
             WHERE id = $1
             RETURNING id
            """,
            work_item_id,
            json.dumps(metadata),
        )
        if updated is None:
            raise HTTPException(status_code=500, detail="Work item update failed")
        await conn.execute(
            """
            INSERT INTO public.alpha_agent_work_item_events (
                work_item_id, event_type, actor, from_status, to_status,
                message, metadata
            )
            VALUES ($1, 'status_changed', $2, 'handoff_ready', 'done', $3, $4::jsonb)
            """,
            work_item_id,
            actor,
            "handoff approved from ChatOps",
            json.dumps(metadata),
        )
    logger.info("mattermost_board_handoff_approved ok work_item_id=%s", work_item_id)
    return f"**Alpha Agent Board**\nMarked `{work_item_id}` done: {current['title']}"


def _bounded_limit(args: tuple[str, ...], *, default: int, maximum: int) -> int:
    if not args:
        return default
    try:
        value = int(args[0])
    except ValueError:
        return default
    return max(1, min(value, maximum))


def _jsonb(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)
