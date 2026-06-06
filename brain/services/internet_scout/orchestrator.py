"""Planning-only orchestrator for Beacon P1."""

from __future__ import annotations

from brain.services.internet_scout.models import InternetScoutPlan, InternetScoutRequest
from brain.services.internet_scout.policy import evaluate_policy, select_tool


class InternetScoutOrchestrator:
    """Build a safe execution plan without performing outbound internet calls."""

    def plan(self, request: InternetScoutRequest) -> InternetScoutPlan:
        selected_tool = select_tool(request)
        decision = evaluate_policy(request)
        notes = [
            "P1 is planning-only; outbound search, fetch, crawl, and browser "
            "execution are not wired in Brain.",
            "Future public egress must execute through Gateway-owned endpoints.",
        ]
        return InternetScoutPlan(
            request=request,
            selected_tool=selected_tool,
            decision=decision,
            execution_enabled=False,
            gateway_required=True,
            notes=notes,
        )
