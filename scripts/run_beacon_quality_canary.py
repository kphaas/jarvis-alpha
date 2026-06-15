#!/usr/bin/env python3
"""Run and persist the scheduled Beacon quality canary."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _writer_dsn() -> str:
    from brain.db.dsn import ensure_writer_password
    from jarvis_common.secrets import get_secret

    dsn = os.getenv("ALPHA_DB_DSN_WRITER") or os.getenv("ALPHA_DB_DSN")
    if not dsn:
        try:
            dsn = get_secret("ALPHA_DB_DSN_WRITER")
        except KeyError:
            dsn = get_secret("ALPHA_DB_DSN")
    return ensure_writer_password(dsn)


async def _run() -> dict[str, object]:
    from brain.db.pool import close_pool, init_pool
    from brain.db.rls import platform_admin_connection
    from brain.services.internet_scout.quality_canary import run_quality_canary_once

    pool = await init_pool(_writer_dsn())
    try:
        async with platform_admin_connection(
            source="scheduled",
            audit_actor="beacon_quality_canary",
            pool=pool,
        ) as conn:
            return await run_quality_canary_once(conn)
    finally:
        await close_pool()


def main() -> int:
    payload = asyncio.run(_run())
    print(json.dumps(payload, sort_keys=True))
    return 1 if payload.get("status") != "passed" else 0


if __name__ == "__main__":
    sys.exit(main())
