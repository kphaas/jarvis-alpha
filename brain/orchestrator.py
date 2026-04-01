"""
Jarvis-Alpha Brain — Unified Orchestrator
Replaces jarvis-core router.py + adaptive_router.py.
All requests (real-time and overnight) enter here.
GitHub issue #2
"""

from typing import Any, AsyncIterator, Optional
from uuid import UUID


class Orchestrator:
    """
    Single entry point for all requests.
    Routes to Planner for task decomposition or
    directly to ModelRouter for simple queries.
    """

    def __init__(self, planner, model_router, memory_manager, buddy):
        """
        Args:
            planner: Planner instance
            model_router: ModelRouter instance
            memory_manager: MemoryManager instance
            buddy: BuddyAgent instance
        """
        pass

    async def handle_request(
        self,
        intent: str,
        user_id: UUID,
        thread_id: UUID,
        project_id: Optional[str] = None,
        stream: bool = False,
    ) -> dict:
        """
        Main entry point. Scores complexity, routes to
        Planner (complex) or ModelRouter (simple).
        Returns structured response dict.
        """
        pass

    def score_complexity(self, intent: str) -> int:
        """
        Returns complexity score 1-5.
        1-2: simple/conversational → ModelRouter direct
        3: research needed → Perplexity via Gateway
        4+: multi-step → Planner + TaskGraph
        """
        pass

    async def stream_response(self, task_id: UUID) -> AsyncIterator[Any]:
        """
        Async generator. Yields partial outputs from
        TaskGraph step execution via SSE.
        """
        pass
