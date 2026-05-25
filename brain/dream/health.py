"""Dream Mode runtime health helpers."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from temporalio.client import Client

from brain.dream.client import temporal_namespace, temporal_target
from brain.dream.task_queues import DREAM_WORKFLOW_QUEUE

HEARTBEAT_PATH = Path(
    os.environ.get(
        "DREAM_TEMPORAL_WORKER_HEARTBEAT",
        str(Path.home() / "jarvis-alpha" / "logs" / "temporal_worker_heartbeat.json"),
    )
)
HEARTBEAT_STALE_AFTER_S = 90


async def heartbeat_loop(interval_s: int = 30) -> None:
    while True:
        write_worker_heartbeat()
        await asyncio.sleep(interval_s)


def write_worker_heartbeat() -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(
        json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "target": temporal_target(),
                "namespace": temporal_namespace(),
                "task_queue": DREAM_WORKFLOW_QUEUE,
            },
            sort_keys=True,
        )
        + "\n"
    )


def read_worker_heartbeat(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if not HEARTBEAT_PATH.exists():
        return {
            "present": False,
            "fresh": False,
            "age_s": None,
            "path": str(HEARTBEAT_PATH),
        }
    stat = HEARTBEAT_PATH.stat()
    age_s = max(0.0, now.timestamp() - stat.st_mtime)
    try:
        payload = json.loads(HEARTBEAT_PATH.read_text())
    except json.JSONDecodeError:
        payload = {}
    return {
        "present": True,
        "fresh": age_s <= HEARTBEAT_STALE_AFTER_S,
        "age_s": round(age_s, 3),
        "path": str(HEARTBEAT_PATH),
        "payload": payload,
    }


async def temporal_server_reachable(timeout_s: float = 2.0) -> bool:
    try:
        await asyncio.wait_for(
            Client.connect(temporal_target(), namespace=temporal_namespace()),
            timeout=timeout_s,
        )
    except Exception:
        return False
    return True
