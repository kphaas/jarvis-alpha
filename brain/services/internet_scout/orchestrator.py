"""Planning orchestrator for Beacon."""

from __future__ import annotations

from brain.services.internet_scout.models import InternetScoutPlan, InternetScoutRequest
from brain.services.internet_scout.policy import evaluate_policy, select_tool
from brain.services.internet_scout.research_planner import plan_research


class InternetScoutOrchestrator:
    """Build a safe execution plan before Gateway-owned egress."""

    def plan(self, request: InternetScoutRequest) -> InternetScoutPlan:
        selected_tool = select_tool(request)
        decision = evaluate_policy(request)
        research = plan_research(request, selected_tool=selected_tool)
        notes = [
            "Brain owns Beacon policy and evidence contracts.",
            "Public internet egress must execute through Gateway-owned endpoints.",
            *research.notes,
        ]
        return InternetScoutPlan(
            request=request,
            selected_tool=selected_tool,
            decision=decision,
            research=research,
            execution_enabled=decision.allowed,
            gateway_required=True,
            notes=notes,
        )
