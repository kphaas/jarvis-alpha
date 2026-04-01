"""
Jarvis-Alpha Brain — Model Router
Selects LLM and tool per task step based on
complexity, keywords, and cost constraints.
GitHub issue #2
"""

from uuid import UUID


class ModelRouter:
    """
    Routes each step to the appropriate model and tool.
    Enforces budget limits. Logs routing decisions.
    Prefers local models (≥80% target).
    """

    def __init__(self, db, gateway_url: str, budget_enforcer):
        """
        Args:
            db: database connection
            gateway_url: Gateway base URL from node_addresses.py
            budget_enforcer: BudgetEnforcer instance
        """
        pass

    def select_model(self, step: dict) -> tuple[str, str]:
        """
        Returns (model_name, target) tuple.
        Complexity 1-2 → local Ollama
        Complexity 3   → Perplexity via Gateway
        Complexity 4+  → Claude via Gateway
        Code keywords  → Qwen local
        Returns: ("llama3.1:8b", "local") or ("claude-haiku", "gateway")
        """
        pass

    async def route(
        self,
        step_id: UUID,
        step: dict,
        user_id: UUID,
    ) -> dict:
        """
        Selects model, calls appropriate adapter,
        logs to routing_decisions and cloud_costs.
        Returns response dict with output and cost_usd.
        """
        pass

    def enforce_budget(self, model: str, estimated_cost: float) -> bool:
        """
        Returns True if call is within budget.
        False triggers fallback to local model.
        """
        pass
