#!/usr/bin/env python3
"""Run and persist the scheduled Beacon quality canary."""

from __future__ import annotations

import asyncio
import asyncpg
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _configure_default_secrets_file() -> None:
    if os.getenv("SECRETS_FILE"):
        return
    operator_secrets = Path.home() / "jarvis" / ".secrets"
    if operator_secrets.exists():
        os.environ["SECRETS_FILE"] = str(operator_secrets)


_configure_default_secrets_file()


def _writer_dsn() -> str:
    from brain.db.dsn import ensure_writer_password
    from jarvis_common.secrets import get_secret

    dsn = os.getenv("ALPHA_DB_DSN_WRITER") or os.getenv("ALPHA_DB_DSN")
    if not dsn:
        try:
            dsn = get_secret("ALPHA_DB_DSN_WRITER")
        except KeyError:
            dsn = get_secret("ALPHA_DB_DSN")
    return _normalize_loopback_dsn(ensure_writer_password(dsn))


def _normalize_loopback_dsn(dsn: str) -> str:
    parsed = urlsplit(dsn)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname != "localhost"
    ):
        return dsn

    userinfo, separator, hostport = parsed.netloc.rpartition("@")
    userinfo_prefix = f"{userinfo}@" if separator else ""
    port_suffix = ""
    if parsed.port is not None:
        port_suffix = f":{parsed.port}"
    elif hostport.startswith("localhost:"):
        port_suffix = hostport.removeprefix("localhost")
    return urlunsplit(
        (
            parsed.scheme,
            f"{userinfo_prefix}127.0.0.1{port_suffix}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


async def _create_canary_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=1, max_size=1)


async def _run() -> dict[str, object]:
    from brain.db.rls import platform_admin_connection
    from brain.services.internet_scout.quality_canary import run_quality_canary_once

    pool = await _create_canary_pool(_writer_dsn())
    try:
        async with platform_admin_connection(
            source="scheduled",
            audit_actor="beacon_quality_canary",
            pool=pool,
        ) as conn:
            return await run_quality_canary_once(conn)
    finally:
        await pool.close()


def main() -> int:
    payload = asyncio.run(_run())
    print(json.dumps(payload, sort_keys=True))
    return 1 if payload.get("status") != "passed" else 0


if __name__ == "__main__":
    sys.exit(main())
