"""Beacon execution service for reviewed search/fetch egress."""

from __future__ import annotations

from fastapi import HTTPException

from brain.services.internet_scout.evidence import (
    packet_from_fetch_response,
    packet_from_search_response,
)
from brain.services.internet_scout.gateway_client import InternetScoutGatewayClient
from brain.services.internet_scout.models import (
    InternetEvidencePacket,
    InternetScoutRequest,
    InternetTool,
    PolicyDecision,
)
from brain.services.internet_scout.policy import evaluate_policy
from brain.services.internet_scout.safety import DEFAULT_MAX_CONTENT_BYTES


class InternetScoutExecutor:
    """Execute only P2-approved Beacon tools through Gateway."""

    def __init__(
        self, gateway_client: InternetScoutGatewayClient | None = None
    ) -> None:
        self.gateway_client = gateway_client or InternetScoutGatewayClient()

    async def execute(
        self,
        request: InternetScoutRequest,
    ) -> tuple[PolicyDecision, InternetEvidencePacket]:
        decision = evaluate_policy(request)
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "beacon_policy_denied",
                    "decision": decision.model_dump(mode="json"),
                },
            )

        if decision.tool == InternetTool.SEARCH:
            if request.query is None:
                raise HTTPException(status_code=400, detail="query is required")
            search_response = await self.gateway_client.search(query=request.query)
            return decision, packet_from_search_response(
                request=request,
                response=search_response,
            )

        if decision.tool in (InternetTool.FETCH, InternetTool.EXTRACT):
            if not request.urls:
                raise HTTPException(status_code=400, detail="url is required")
            fetch_response = await self.gateway_client.fetch(
                url=request.urls[0],
                max_bytes=DEFAULT_MAX_CONTENT_BYTES,
            )
            return decision, packet_from_fetch_response(
                request=request,
                response=fetch_response,
            )

        raise HTTPException(
            status_code=403,
            detail=f"Beacon tool {decision.tool.value!r} is not enabled in P2",
        )
