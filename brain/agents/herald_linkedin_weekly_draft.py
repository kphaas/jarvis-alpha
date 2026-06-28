from __future__ import annotations

import argparse
import asyncio
import os

from jarvis_common.logging_config import get_logger

from brain.config.secrets import get_secret
from brain.db.dsn import ensure_writer_password
from brain.db.pool import close_pool, get_pool, init_pool
from brain.services.herald_social import create_weekly_linkedin_draft_if_due

logger = get_logger("alpha_herald_linkedin_weekly_draft")


def _dsn() -> str:
    value = os.environ.get("ALPHA_DB_DSN_WRITER", "").strip()
    if value:
        return ensure_writer_password(value)
    return ensure_writer_password(get_secret("ALPHA_DB_DSN_WRITER"))


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create one due Herald LinkedIn weekly draft"
    )
    parser.add_argument(
        "--trigger",
        choices=("manual", "scheduled", "smoke"),
        default=os.environ.get("HERALD_LINKEDIN_WEEKLY_TRIGGER", "scheduled"),
    )
    return parser.parse_args()


async def run_once(*, trigger: str):
    await init_pool(_dsn())
    try:
        async with get_pool().acquire() as conn:
            outcome = await create_weekly_linkedin_draft_if_due(
                conn,
                actor_sub=f"herald-linkedin-weekly:{trigger}",
            )
        logger.info(
            "herald linkedin weekly draft check completed",
            extra={
                "trigger": trigger,
                "draft_created": outcome.created,
                "reason": outcome.reason,
                "request_id": str(outcome.request_id) if outcome.request_id else None,
                "variant_id": str(outcome.variant_id) if outcome.variant_id else None,
            },
        )
        return outcome
    finally:
        await close_pool()


def main() -> None:
    args = _args()
    asyncio.run(run_once(trigger=args.trigger))


if __name__ == "__main__":
    main()
