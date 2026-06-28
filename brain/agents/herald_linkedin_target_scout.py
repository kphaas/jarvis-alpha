from __future__ import annotations

import argparse
import asyncio
import os

from jarvis_common.logging_config import get_logger

from brain.config.secrets import get_secret
from brain.db.dsn import ensure_writer_password
from brain.db.pool import close_pool, get_pool, init_pool
from brain.services.herald_social import scout_linkedin_engagement_targets

logger = get_logger("alpha_herald_linkedin_target_scout")


def _dsn() -> str:
    value = os.environ.get("ALPHA_DB_DSN_WRITER", "").strip()
    if value:
        return ensure_writer_password(value)
    return ensure_writer_password(get_secret("ALPHA_DB_DSN_WRITER"))


def _topics() -> tuple[str, ...] | None:
    raw = os.environ.get("HERALD_LINKEDIN_TARGET_TOPICS", "")
    topics = tuple(part.strip() for part in raw.split(",") if part.strip())
    return topics or None


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scout public LinkedIn engagement targets for Herald"
    )
    parser.add_argument(
        "--trigger",
        choices=("manual", "scheduled", "smoke"),
        default=os.environ.get("HERALD_LINKEDIN_TARGET_TRIGGER", "scheduled"),
    )
    return parser.parse_args()


async def run_once(*, trigger: str):
    await init_pool(_dsn())
    try:
        async with get_pool().acquire() as conn:
            outcome = await scout_linkedin_engagement_targets(
                conn,
                actor_sub=f"herald-linkedin-target-scout:{trigger}",
                topics=_topics(),
            )
        logger.info(
            "herald linkedin target scout completed",
            extra={
                "trigger": trigger,
                "target_count": outcome.created_count,
                "skipped_count": outcome.skipped_count,
                "reason": outcome.reason,
                "item_ids": [str(item_id) for item_id in outcome.item_ids],
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
