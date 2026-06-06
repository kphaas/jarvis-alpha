"""Planning orchestrator for Beacon."""

from __future__ import annotations

from brain.services.internet_scout.models import InternetScoutPlan, InternetScoutRequest
from brain.services.internet_scout.policy import evaluate_policy, select_tool


class InternetScoutOrchestrator:
    """Build a safe execution plan before Gateway-owned egress."""

    def plan(self, request: InternetScoutRequest) -> InternetScoutPlan:
        selected_tool = select_tool(request)
        decision = evaluate_policy(request)
        notes = [
            "Brain owns Beacon policy and evidence contracts.",
            "Public internet egress must execute through Gateway-owned endpoints.",
        ]
        return InternetScoutPlan(
            request=request,
            selected_tool=selected_tool,
            decision=decision,
            execution_enabled=decision.allowed,
            gateway_required=True,
            notes=notes,
        )
