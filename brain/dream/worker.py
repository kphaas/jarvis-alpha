"""Temporal worker bootstrap for Dream Mode."""

from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from brain.db.pool import close_pool, init_pool
from brain.dream.activities import (
    flush_cleanup_activity,
    persist_plan_activity,
    plan_session_activity,
    review_plan_activity,
)
from brain.dream.client import temporal_namespace, temporal_target
from brain.dream.health import heartbeat_loop
from brain.dream.task_queues import DREAM_WORKFLOW_QUEUE
from brain.dream.workflows import DreamSessionWorkflow
from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_dream_worker")

TEMPORAL_WORKFLOWS = [DreamSessionWorkflow]
TEMPORAL_ACTIVITIES = [
    plan_session_activity,
    review_plan_activity,
    persist_plan_activity,
    flush_cleanup_activity,
]


def _writer_dsn() -> str:
    return os.environ.get("ALPHA_DB_DSN_WRITER") or get_secret("ALPHA_DB_DSN_WRITER")


async def run_worker() -> None:
    await init_pool(_writer_dsn())
    try:
        target = temporal_target()
        namespace = temporal_namespace()
        logger.info(
            "starting Dream Temporal worker target=%s namespace=%s task_queue=%s",
            target,
            namespace,
            DREAM_WORKFLOW_QUEUE,
        )
        client = await Client.connect(target, namespace=namespace)
        worker = Worker(
            client,
            task_queue=DREAM_WORKFLOW_QUEUE,
            workflows=TEMPORAL_WORKFLOWS,
            activities=TEMPORAL_ACTIVITIES,
        )
        heartbeat_task = asyncio.create_task(heartbeat_loop())
        await worker.run()
    finally:
        if "heartbeat_task" in locals():
            heartbeat_task.cancel()
        await close_pool()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
