import os
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger("jarvis.db")

DSN = os.getenv("JARVIS_ALPHA_DSN", "")


@asynccontextmanager
async def get_raw_connection():
    """
    Stub: yields None in Alpha-1. Replace with asyncpg pool in Alpha-2.
    RLS middleware handles None gracefully.
    """
    logger.debug("db.session: stub connection — DSN not yet wired")
    yield None
