"""
Jarvis-Alpha Brain — Buddy Agent
Always-on companion. Monitors TaskGraph and memory.
Generates alerts, reminders, and suggestions.
Never executes heavy tasks — delegates to Planner.
GitHub issue #2
"""

import asyncio  # noqa: F401
from typing import Optional
from uuid import UUID


class BuddyAgent:
    """
    Async polling loop that runs continuously on Brain.
    Reads TaskGraph + memory for all users.
    Writes to buddy_state. Pushes notifications to UI + Voice.
    Emits heartbeat every poll cycle.
    """

    POLL_INTERVAL_SECONDS = 30
    NOTIFICATION_COOLDOWN_SECONDS = 300

    def __init__(self, db, memory_manager, task_graph, thread_manager):
        """
        Args:
            db: database connection
            memory_manager: MemoryManager instance
            task_graph: TaskGraph instance
            thread_manager: ThreadManager instance
        """
        pass

    async def run_loop(self):
        """
        Main async loop. Each cycle:
        1. Emit heartbeat to buddy_state
        2. Check for pending retention prompts
        3. Check for failed/deferred tasks
        4. Generate suggestions from memory
        5. Push notifications
        6. Sleep POLL_INTERVAL_SECONDS
        Uses SELECT FOR UPDATE SKIP LOCKED on all polling queries.
        """
        pass

    async def emit_heartbeat(self, user_id: UUID):
        """
        Updates buddy_state.heartbeat_at = NOW().
        Dashboard checks this to detect silent Buddy death.
        """
        pass

    async def check_retention_due(self) -> list[dict]:
        """
        Finds threads idle > 30 days with no open retention prompt.
        Creates thread_retention_prompts rows.
        Returns list of triggered prompts.
        """
        pass

    async def push_notification(
        self,
        user_id: UUID,
        message: str,
        notification_type: str,
        thread_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
    ):
        """
        Writes alert to buddy_state.alerts JSONB.
        notification_type: retention_prompt | task_failed |
                           task_complete | suggestion | reminder
        Respects NOTIFICATION_COOLDOWN_SECONDS per task/thread.
        """
        pass

    async def generate_suggestions(self, user_id: UUID) -> list[str]:
        """
        Reads recent memory + active tasks.
        Returns list of proactive suggestion strings.
        Delegates execution to Planner — never runs tasks directly.
        """
        pass
