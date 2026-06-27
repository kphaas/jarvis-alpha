from __future__ import annotations

import argparse
import os
import sys

from jarvis_common.logging_config import get_logger

from brain.services.herald_linkedin_health import check_linkedin_token_health

logger = get_logger("alpha_herald_linkedin_health")


def _fail_on_degraded() -> bool:
    return os.environ.get("AT0_LINKEDIN_HEALTH_FAIL_ON_DEGRADED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one Herald LinkedIn token health check"
    )
    parser.add_argument(
        "--trigger",
        choices=("manual", "scheduled", "smoke"),
        default=os.environ.get("AT0_LINKEDIN_HEALTH_TRIGGER", "scheduled"),
    )
    return parser.parse_args()


def main() -> None:
    args = _args()
    health = check_linkedin_token_health()
    logger.info(
        "herald linkedin token health check completed",
        extra={
            "status": health.status,
            "checked_at": health.checked_at.isoformat(),
            "trigger": args.trigger,
            "active": health.active,
            "seconds_remaining": health.seconds_remaining,
            "scopes": health.scopes,
            "missing_scopes": health.missing_scopes,
            "error_type": health.error_type,
        },
    )
    if health.requires_attention and _fail_on_degraded():
        sys.exit(1)


if __name__ == "__main__":
    main()
