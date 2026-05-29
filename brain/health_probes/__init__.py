"""Readiness probes for the Brain /health/ready endpoint (AUDIT-3).

Each probe performs a fresh (uncached) check of one critical dependency and
returns a ProbeResult. Probes never raise: timeouts and exceptions are caught
and surfaced as ok=False with a short last_error_msg. The route layer decides
HTTP 200 vs 503 from the aggregate.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx
from temporalio.client import Client

from brain.core.config import OLLAMA_URL
from brain.db.pool import get_pool
from brain.dream.client import temporal_namespace, temporal_target

# Per-check timeout budgets (seconds).
# DB + Ollama use the uniform 200ms readiness budget. Temporal is an explicit
# exception: a cold gRPC Client.connect() routinely exceeds 200ms even on a
# healthy server (the existing temporal_server_reachable() helper uses 2.0s for
# the same reason). 1.0s balances false-positive reduction against a bounded
# /health/ready max latency. See TD: persistent Temporal client singleton.
DB_TIMEOUT_S = 0.2
OLLAMA_TIMEOUT_S = 0.2
TEMPORAL_TIMEOUT_S = 1.0


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: int
    last_error_msg: str | None = None


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


async def _run(coro_factory, timeout_s: float) -> ProbeResult:
    """Run a probe coroutine under a timeout, never raising.

    coro_factory is a zero-arg callable returning the awaitable to probe, so the
    coroutine is created inside the try (cheap, and keeps construction failures
    inside the same error path).
    """
    start = time.monotonic()
    try:
        await asyncio.wait_for(coro_factory(), timeout=timeout_s)
        return ProbeResult(ok=True, latency_ms=_elapsed_ms(start))
    except (asyncio.TimeoutError, TimeoutError):
        return ProbeResult(
            ok=False,
            latency_ms=_elapsed_ms(start),
            last_error_msg=f"timeout after {int(timeout_s * 1000)}ms",
        )
    except Exception as e:  # noqa: BLE001 — status-report probe, must not raise
        return ProbeResult(
            ok=False, latency_ms=_elapsed_ms(start), last_error_msg=str(e)[:200]
        )


async def probe_db_pool() -> ProbeResult:
    """Acquire a pooled connection and run a trivial query."""

    async def _check() -> None:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")

    return await _run(_check, DB_TIMEOUT_S)


async def probe_ollama() -> ProbeResult:
    """Ping the local Ollama daemon (no inference) via /api/version."""

    async def _check() -> None:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_S) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/version")
            resp.raise_for_status()

    return await _run(_check, OLLAMA_TIMEOUT_S)


async def probe_temporal() -> ProbeResult:
    """Connect to the Temporal frontend (cold gRPC connect — see TEMPORAL_TIMEOUT_S)."""

    async def _check() -> None:
        await Client.connect(temporal_target(), namespace=temporal_namespace())

    return await _run(_check, TEMPORAL_TIMEOUT_S)
