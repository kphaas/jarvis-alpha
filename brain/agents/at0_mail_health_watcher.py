from __future__ import annotations

import argparse
import asyncio
import os
import sys

from jarvis_common.logging_config import get_logger

from brain.config.secrets import get_secret
from brain.db.dsn import ensure_writer_password
from brain.db.pool import close_pool, init_pool
from brain.services.at0_mail_health import check_at0_mail_graph_health

logger = get_logger("alpha_at0_mail_health")


def _dsn() -> str:
    value = os.environ.get("ALPHA_DB_DSN_WRITER", "").strip()
    if value:
        return ensure_writer_password(value)
    return ensure_writer_password(get_secret("ALPHA_DB_DSN_WRITER"))


def _fail_on_degraded() -> bool:
    return os.environ.get("AT0_HERALD_HEALTH_FAIL_ON_DEGRADED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one AT-0 Herald Microsoft Graph health check"
    )
    parser.add_argument(
        "--trigger",
        choices=("manual", "scheduled", "smoke"),
        default=os.environ.get("AT0_HERALD_HEALTH_TRIGGER", "scheduled"),
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=int(os.environ.get("AT0_HERALD_HEALTH_MAX_RESULTS", "1")),
    )
    return parser.parse_args()


async def run_once(*, trigger: str, max_results: int):
    await init_pool(_dsn())
    try:
        health = await check_at0_mail_graph_health(
            trigger=trigger,
            max_results=max_results,
        )
        logger.info(
            "at0 herald graph health check completed",
            extra={
                "status": health.status,
                "checked_at": health.checked_at.isoformat(),
                "trigger": trigger,
                "mailboxes_checked": health.mailboxes_checked,
                "messages_seen": health.messages_seen,
                "graph_roles": health.graph_roles,
                "missing_graph_roles": health.missing_graph_roles,
                "current_send_failures": health.current_send_failures,
                "stuck_sending_count": health.stuck_sending_count,
                "last_sent_at": (
                    health.last_sent_at.isoformat() if health.last_sent_at else None
                ),
                "error_type": health.error_type,
            },
        )
        return health
    except Exception:
        logger.exception(
            "at0 herald graph health check crashed",
            extra={"trigger": trigger, "max_results": max_results},
        )
        raise
    finally:
        await close_pool()


def main() -> None:
    args = _args()
    health = asyncio.run(run_once(trigger=args.trigger, max_results=args.max_results))
    if health.requires_attention and _fail_on_degraded():
        sys.exit(1)


if __name__ == "__main__":
    main()
