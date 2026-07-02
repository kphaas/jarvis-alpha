from __future__ import annotations

import argparse
import asyncio
import os
from datetime import UTC, datetime

from brain.config.secrets import get_secret
from brain.db.dsn import ensure_writer_password
from brain.db.pool import close_pool, get_pool, init_pool
from brain.db.rls import platform_admin_connection
from brain.services.agent_schedules import materialize_due_scheduled_work
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_agent_scheduler")


def _dsn() -> str:
    value = os.environ.get("ALPHA_DB_DSN_WRITER", "").strip()
    if value:
        return ensure_writer_password(value)
    return ensure_writer_password(get_secret("ALPHA_DB_DSN_WRITER"))


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize due Agent Board scheduled work"
    )
    parser.add_argument(
        "--trigger",
        choices=("manual", "scheduled", "smoke"),
        default=os.environ.get("AGENT_SCHEDULER_TRIGGER", "scheduled"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("AGENT_SCHEDULER_LIMIT", "25")),
    )
    return parser.parse_args()


async def run_once(*, trigger: str, limit: int):
    await init_pool(_dsn())
    try:
        async with platform_admin_connection(
            source="scheduled",
            audit_actor=f"agent_scheduler:{trigger}",
            pool=get_pool(),
        ) as conn:
            items = await materialize_due_scheduled_work(
                conn,
                now=datetime.now(UTC),
                limit=limit,
                actor=f"agent_scheduler:{trigger}",
            )
        logger.info(
            "agent scheduler completed",
            extra={
                "trigger": trigger,
                "materialized_count": len(items),
                "schedule_ids": [item.schedule_id for item in items],
                "work_item_ids": [item.work_item_id for item in items],
            },
        )
        return items
    finally:
        await close_pool()


def main() -> None:
    args = _args()
    asyncio.run(run_once(trigger=args.trigger, limit=args.limit))


if __name__ == "__main__":
    main()
