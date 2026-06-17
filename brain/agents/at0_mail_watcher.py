from __future__ import annotations

import argparse
import asyncio
import os

from jarvis_common.logging_config import get_logger

from brain.config.secrets import get_secret
from brain.db.dsn import ensure_writer_password
from brain.db.pool import close_pool, init_pool
from brain.services.at0_mail_agent import scan_at0_mail

logger = get_logger("alpha_at0_mail")


def _dsn() -> str:
    value = os.environ.get("ALPHA_DB_DSN_WRITER", "").strip()
    if value:
        return ensure_writer_password(value)
    return ensure_writer_password(get_secret("ALPHA_DB_DSN_WRITER"))


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one AT-0 Herald mail scan")
    parser.add_argument(
        "--max-results",
        type=int,
        default=int(os.environ.get("AT0_HERALD_MAX_RESULTS", "25")),
    )
    parser.add_argument(
        "--trigger",
        choices=("api", "manual", "scheduled", "smoke"),
        default=os.environ.get("AT0_HERALD_TRIGGER", "scheduled"),
    )
    return parser.parse_args()


async def run_once(*, max_results: int, trigger: str) -> None:
    bounded_max = max(1, min(max_results, 50))
    await init_pool(_dsn())
    try:
        result = await scan_at0_mail(max_results=bounded_max, trigger=trigger)
        logger.info(
            "at0 herald mail scan completed",
            extra={
                "scan_run_id": result.scan_run_id,
                "trigger": trigger,
                "mailboxes_scanned": result.mailboxes_scanned,
                "messages_seen": result.messages_seen,
                "messages_new": result.messages_new,
                "draft_proposals_created": result.draft_proposals_created,
            },
        )
    except Exception:
        logger.exception(
            "at0 herald mail scan failed",
            extra={"trigger": trigger, "max_results": bounded_max},
        )
        raise
    finally:
        await close_pool()


def main() -> None:
    args = _args()
    asyncio.run(run_once(max_results=args.max_results, trigger=args.trigger))


if __name__ == "__main__":
    main()
