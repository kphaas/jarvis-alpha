"""
Jarvis-Alpha Brain — Thread Manager
Manages chat threads, message storage and
the 30-day retention policy.
GitHub issue #2
"""

from typing import Optional
from uuid import UUID


MAX_PERSONAL_THREADS = 7
MAX_PROJECT_THREADS = 5
MAX_PROJECTS = 5
RETENTION_DAYS = 30


class ThreadManager:
    """
    Enforces thread limits per user and project.
    Handles message storage and retention lifecycle.
    Delegates memory extraction to MemoryManager.
    """

    def __init__(self, db, memory_manager):
        """
        Args:
            db: database connection
            memory_manager: MemoryManager instance for extraction
        """
        pass

    async def can_create_thread(
        self,
        user_id: UUID,
        project_id: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Checks limits before creating a thread.
        Personal: max 7 WHERE project_id IS NULL
        Project: max 5 per project_id, max 5 distinct projects
        Returns (allowed: bool, reason: str).
        """
        pass

    async def create_thread(
        self,
        user_id: UUID,
        title: str,
        thread_type: str,
        project_id: Optional[str] = None,
    ) -> UUID:
        """
        Creates chat_threads row after limit check.
        Returns thread_id.
        Raises ValueError if limit exceeded.
        """
        pass

    async def add_message(
        self,
        thread_id: UUID,
        role: str,
        content: str,
        model_used: Optional[str] = None,
        tokens_used: Optional[int] = None,
    ) -> UUID:
        """
        Inserts into chat_messages.
        Updates chat_threads.last_active_at = NOW().
        Returns message_id.
        """
        pass

    async def check_retention_due(self) -> list[dict]:
        """
        Finds threads where:
        last_active_at < NOW() - INTERVAL '30 days'
        AND no open retention prompt exists
        AND archived = FALSE
        Returns list of thread dicts.
        """
        pass

    async def extract_and_delete(self, thread_id: UUID, user_id: UUID):
        """
        1. Fetches all messages for thread
        2. Calls MemoryManager.store() with source=thread_extract
        3. Writes to thread_memory_extracts
        4. DELETEs chat_messages (CASCADE from thread FK)
        5. Sets chat_threads.archived=TRUE, memory_extracted=TRUE
        """
        pass

    async def handle_retention_response(
        self,
        prompt_id: UUID,
        user_id: UUID,
        response: str,
    ):
        """
        Processes user response to retention prompt.
        response: extract_and_delete | keep | delete_only | snooze
        Updates thread_retention_prompts.user_response + responded_at.
        """
        pass
