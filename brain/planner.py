"""
Jarvis-Alpha Brain — Task Planner
Decomposes intents into TaskGraph steps.
Works for both real-time and overnight tasks.
GitHub issue #2
"""

from typing import Optional
from uuid import UUID


class Planner:
    """
    Decomposes high-level intents into ordered task steps.
    Assigns model and tool per step.
    Inserts into agent_tasks and task_steps tables.
    """

    def __init__(self, db, model_router, gap_detector):
        """
        Args:
            db: database connection
            model_router: ModelRouter instance
            gap_detector: GapDetector instance
        """
        pass

    async def create_task(
        self,
        intent: str,
        user_id: UUID,
        project_id: Optional[str] = None,
        priority: int = 3,
    ) -> UUID:
        """
        Creates agent_tasks row. Returns task_id.
        Enforces max task limits per project.
        """
        pass

    async def decompose(self, task_id: UUID) -> list[dict]:
        """
        Breaks task into steps. Each step dict contains:
        step_order, model, tool, input_json.
        Inserts into task_steps table.
        Returns list of step dicts.
        """
        pass

    async def auto_split_if_large(self, task_id: UUID, iteration_cap: int = 10):
        """
        If decomposed steps exceed iteration_cap,
        splits into sub-tasks automatically.
        Prevents overnight agent deferral.
        """
        pass
