from __future__ import annotations

import asyncio
import os

from jarvis_common.logging_config import get_logger

from brain.config.secrets import get_secret
from brain.db.pool import close_pool, init_pool
from brain.services.school_email_agent import scan_school_email

logger = get_logger("alpha_school_email")


def _dsn() -> str:
    value = os.environ.get("ALPHA_DB_DSN_WRITER", "").strip()
    if value:
        return value
    return get_secret("ALPHA_DB_DSN_WRITER").strip()


async def run_once() -> None:
    await init_pool(_dsn())
    try:
        result = await scan_school_email(
            max_results=int(os.environ.get("ALPHA_SCHOOL_EMAIL_MAX_RESULTS", "25"))
        )
        logger.info(
            (
                "SCHOOL_EMAIL_SCAN rules=%s queries=%s seen=%s new=%s "
                "events_created=%s actions_created=%s events_imported=%s "
                "actions_imported=%s import_errors=%s existing=%s"
            ),
            result.rules_loaded,
            result.queries_run,
            result.messages_seen,
            result.messages_new,
            result.event_candidates_created,
            result.action_candidates_created,
            result.events_imported,
            result.actions_imported,
            result.import_errors,
            result.candidates_existing,
        )
    finally:
        await close_pool()


def main() -> None:
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
