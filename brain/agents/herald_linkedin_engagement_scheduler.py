from __future__ import annotations

import argparse
import asyncio
import os

from jarvis_common.logging_config import get_logger

from brain.config.secrets import get_secret
from brain.db.dsn import ensure_writer_password
from brain.db.pool import close_pool, get_pool, init_pool
from brain.services.herald_social import draft_linkedin_engagement_replies_if_due

logger = get_logger("alpha_herald_linkedin_engagement_scheduler")


def _dsn() -> str:
    value = os.environ.get("ALPHA_DB_DSN_WRITER", "").strip()
    if value:
        return ensure_writer_password(value)
    return ensure_writer_password(get_secret("ALPHA_DB_DSN_WRITER"))


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create due Herald LinkedIn engagement reply drafts"
    )
    parser.add_argument(
        "--trigger",
        choices=("manual", "scheduled", "smoke"),
        default=os.environ.get("HERALD_LINKEDIN_ENGAGEMENT_TRIGGER", "scheduled"),
    )
    return parser.parse_args()


async def run_once(*, trigger: str):
    await init_pool(_dsn())
    try:
        async with get_pool().acquire() as conn:
            outcome = await draft_linkedin_engagement_replies_if_due(
                conn,
                actor_sub=f"herald-linkedin-engagement:{trigger}",
            )
        logger.info(
            "herald linkedin engagement scheduler completed",
            extra={
                "trigger": trigger,
                "draft_count": outcome.created_count,
                "reason": outcome.reason,
                "item_ids": [str(item_id) for item_id in outcome.item_ids],
                "variant_ids": [str(variant_id) for variant_id in outcome.variant_ids],
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
