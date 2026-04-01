"""
Jarvis-Alpha Brain — Multi-Tier Memory Manager
Handles short-term, long-term, execution-state,
and thread-extract memory.
GitHub issue #2
"""

from typing import Optional
from uuid import UUID


class MemoryManager:
    """
    Manages all memory tiers in conversation_memory.
    Injects relevant context per step.
    Tags sources: live, thread_extract, overnight, ingest.
    """

    def __init__(self, db, embedding_model):
        """
        Args:
            db: database connection
            embedding_model: sentence-transformer model for vector encoding
        """
        pass

    async def fetch_context(
        self,
        user_id: UUID,
        intent: str,
        project_id: Optional[str] = None,
        include_extracts: bool = False,
    ) -> list[dict]:
        """
        Retrieves relevant memories via vector similarity search.
        Excludes thread_extracts by default.
        include_extracts=True for explicit recall queries.
        """
        pass

    async def store(
        self,
        user_id: UUID,
        summary: str,
        source: str = "live",
        project_id: Optional[str] = None,
        source_thread_id: Optional[UUID] = None,
        structured_data: Optional[dict] = None,
    ) -> UUID:
        """
        Embeds and stores a memory.
        source must be one of: live, thread_extract, overnight, ingest.
        Returns memory id.
        """
        pass

    async def promote(self, memory_id: UUID):
        """
        Marks memory as promoted=True.
        Promoted memories are always included in context.
        """
        pass

    async def store_execution_state(self, step_id: UUID, context: dict):
        """
        Writes per-step snapshot to execution_state table.
        """
        pass

    async def inject_per_step(self, step: dict, user_id: UUID) -> dict:
        """
        Fetches relevant memories for a specific step.
        Returns step dict with memory_context field added.
        """
        pass
