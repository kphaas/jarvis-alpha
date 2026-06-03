from __future__ import annotations

import argparse
import asyncio
import os

from jarvis_common.logging_config import get_logger

from brain.config.secrets import get_secret
from brain.db.dsn import ensure_writer_password
from brain.db.pool import close_pool, init_pool
from brain.services.gmail_oauth_health import check_gmail_oauth_health

logger = get_logger("alpha_gmail_health")


def _dsn() -> str:
    value = os.environ.get("ALPHA_DB_DSN_WRITER", "").strip()
    if value:
        return ensure_writer_password(value)
    return ensure_writer_password(get_secret("ALPHA_DB_DSN_WRITER"))


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one Alpha Gmail OAuth health check"
    )
    parser.add_argument(
        "--trigger",
        choices=("manual", "scheduled"),
        default=os.environ.get("ALPHA_GMAIL_HEALTH_TRIGGER", "scheduled"),
    )
    return parser.parse_args()


async def run_once(*, trigger: str) -> None:
    await init_pool(_dsn())
    try:
        health = await check_gmail_oauth_health(trigger=trigger)
        logger.info(
            "gmail oauth health check completed",
            extra={
                "status": health.status,
                "checked_at": health.checked_at.isoformat()
                if health.checked_at
                else None,
                "last_successful_refresh_at": (
                    health.last_successful_refresh_at.isoformat()
                    if health.last_successful_refresh_at
                    else None
                ),
                "oauth_mode": health.oauth_mode,
                "refresh_token_days_remaining": health.refresh_token_days_remaining,
                "reconnect_recommended": health.reconnect_recommended,
                "error_type": health.error_type,
            },
        )
    finally:
        await close_pool()


def main() -> None:
    args = _args()
    asyncio.run(run_once(trigger=args.trigger))


if __name__ == "__main__":
    main()
