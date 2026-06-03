from __future__ import annotations

import asyncio
import argparse
import os

from jarvis_common.logging_config import get_logger

from brain.config.secrets import get_secret
from brain.db.dsn import ensure_writer_password
from brain.db.pool import close_pool, init_pool
from brain.services.school_email_agent import scan_school_email

logger = get_logger("alpha_school_email")


def _dsn() -> str:
    value = os.environ.get("ALPHA_DB_DSN_WRITER", "").strip()
    if value:
        return ensure_writer_password(value)
    return ensure_writer_password(get_secret("ALPHA_DB_DSN_WRITER"))


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Alpha school email scan")
    parser.add_argument(
        "--max-results",
        type=int,
        default=int(os.environ.get("ALPHA_SCHOOL_EMAIL_MAX_RESULTS", "25")),
    )
    parser.add_argument(
        "--trigger",
        choices=("api", "manual", "nightly"),
        default=os.environ.get("ALPHA_SCHOOL_EMAIL_TRIGGER", "nightly"),
    )
    parser.add_argument(
        "--no-import",
        action="store_true",
        help="Store Alpha candidates without importing approved items to Family",
    )
    return parser.parse_args()


async def run_once(
    *,
    max_results: int,
    trigger: str,
    import_to_family: bool,
) -> None:
    await init_pool(_dsn())
    try:
        result = await scan_school_email(
            max_results=max_results,
            import_to_family=import_to_family,
            trigger=trigger,
        )
        logger.info(
            "school email scan completed",
            extra={
                "scan_run_id": result.scan_run_id,
                "trigger": trigger,
                "rules_loaded": result.rules_loaded,
                "queries_run": result.queries_run,
                "messages_seen": result.messages_seen,
                "messages_new": result.messages_new,
                "event_candidates_created": result.event_candidates_created,
                "action_candidates_created": result.action_candidates_created,
                "events_imported": result.events_imported,
                "actions_imported": result.actions_imported,
                "import_errors": result.import_errors,
                "candidates_existing": result.candidates_existing,
            },
        )
    except Exception:
        logger.exception(
            "school email scan failed",
            extra={"trigger": trigger, "max_results": max_results},
        )
        raise
    finally:
        await close_pool()


def main() -> None:
    args = _args()
    asyncio.run(
        run_once(
            max_results=max(1, min(args.max_results, 500)),
            trigger=args.trigger,
            import_to_family=not args.no_import,
        )
    )


if __name__ == "__main__":
    main()
