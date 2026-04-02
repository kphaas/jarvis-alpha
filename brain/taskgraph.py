"""
Jarvis-Alpha Brain — TaskGraph Manager
Manages DAG execution state for alpha_task_graphs and alpha_task_steps.
GitHub issue #2
"""

from typing import Optional
from uuid import UUID


class TaskGraph:
    """
    Executes task steps in order.
    Tracks status, timing, and output per step.
    Uses SELECT FOR UPDATE SKIP LOCKED for safe concurrent polling.
    """

    def __init__(self, db, sandbox, validator):
        """
        Args:
            db: database connection
            sandbox: Sandbox instance for code/file steps
            validator: Validator instance
        """
        pass

    async def get_next_step(self, task_id: UUID) -> Optional[dict]:
        """
        Returns next pending step using:
        SELECT ... FOR UPDATE SKIP LOCKED
        Prevents duplicate execution across concurrent workers.
        """
        pass

    async def execute_step(self, step_id: UUID) -> dict:
        """
        Runs a single step. Records started_at, completed_at,
        duration_ms. Writes output_ref to alpha_task_steps.
        """
        pass

    async def update_step_status(
        self,
        step_id: UUID,
        status: str,
        output_ref: Optional[str] = None,
        error: Optional[str] = None,
    ):
        """
        Updates alpha_task_steps row. Valid statuses:
        pending, running, completed, failed.
        """
        pass

    async def get_pending_tasks(self, project_id: Optional[str] = None) -> list[dict]:
        """
        Returns all pending alpha_task_graphs.
        Optionally filtered by project_id.
        """
        pass

    async def checkpoint(self, step_id: UUID, context: dict):
        """
        Writes checkpoint on alpha_task_graphs for step.
        Enables resume after failure.
        """
        pass
