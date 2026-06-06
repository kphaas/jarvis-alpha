"""Approval-gated Beacon browser task runner contracts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import HTTPException

from brain.services.internet_scout.evidence import (
    build_evidence_packet,
    build_source_reference,
)
from brain.services.internet_scout.models import (
    BrowserRunObservation,
    BrowserSandboxPolicy,
    EvidenceClaim,
    InternetEvidencePacket,
    InternetScoutBrowserRunResponse,
    InternetScoutPlan,
    InternetScoutRequest,
    InternetTool,
)
from brain.services.internet_scout.policy import evaluate_policy
from brain.services.internet_scout.safety import validate_url


class BrowserRuntimeUnavailableError(RuntimeError):
    """Raised when no reviewed browser runtime is configured."""


class BrowserSandboxPolicyError(ValueError):
    """Raised when a browser task is outside the P8 sandbox."""


class BrowserTaskAdapter(Protocol):
    async def run(
        self,
        *,
        request: InternetScoutRequest,
        sandbox: BrowserSandboxPolicy,
    ) -> list[BrowserRunObservation]:
        """Run the approved task and return reviewed observations."""


class DisabledBrowserTaskAdapter:
    async def run(
        self,
        *,
        request: InternetScoutRequest,
        sandbox: BrowserSandboxPolicy,
    ) -> list[BrowserRunObservation]:
        raise BrowserRuntimeUnavailableError("browser_runtime_not_configured")


class BrowserTaskRunner:
    def __init__(
        self,
        adapter: BrowserTaskAdapter | None = None,
    ) -> None:
        self.adapter = adapter or DisabledBrowserTaskAdapter()

    async def execute(
        self,
        *,
        request_id: UUID,
        approval_queue_id: UUID,
        request: InternetScoutRequest,
        plan: InternetScoutPlan,
        max_steps: int,
        require_screenshot: bool,
    ) -> InternetScoutBrowserRunResponse:
        sandbox = build_browser_sandbox_policy(
            request,
            max_steps=max_steps,
            require_screenshot=require_screenshot,
        )
        observations = await self.adapter.run(request=request, sandbox=sandbox)
        _validate_observations(observations, sandbox)
        packet = packet_from_browser_observations(
            request=request,
            observations=observations,
        )
        return InternetScoutBrowserRunResponse(
            request_id=request_id,
            approval_queue_id=approval_queue_id,
            status="completed",
            plan=plan,
            sandbox=sandbox,
            evidence=packet,
            observations=observations,
            screenshots_review_required=True,
            blocked_reasons=[],
        )


def normalize_browser_request(request: InternetScoutRequest) -> InternetScoutRequest:
    return request.model_copy(
        update={"tool_hint": InternetTool.BROWSER_USE, "needs_interaction": True}
    )


def build_browser_sandbox_policy(
    request: InternetScoutRequest,
    *,
    max_steps: int,
    require_screenshot: bool,
) -> BrowserSandboxPolicy:
    normalized = normalize_browser_request(request)
    decision = evaluate_policy(normalized)
    if decision.tool != InternetTool.BROWSER_USE or not decision.requires_approval:
        raise BrowserSandboxPolicyError("browser_use_request_required")
    if decision.tier != "T4":
        raise BrowserSandboxPolicyError("browser_use_t5_deferred")
    if not require_screenshot:
        raise BrowserSandboxPolicyError("browser_screenshot_required")
    if not normalized.urls:
        raise BrowserSandboxPolicyError("browser_start_url_required")

    hosts: list[str] = []
    for url in normalized.urls:
        safety = validate_url(url)
        if not safety.allowed or safety.host is None:
            raise BrowserSandboxPolicyError("browser_start_url_not_public")
        if safety.host not in hosts:
            hosts.append(safety.host)

    return BrowserSandboxPolicy(
        allowed_hosts=hosts,
        max_steps=max_steps,
        require_screenshot=True,
        allow_downloads=False,
        allow_forms=False,
        allow_cross_host_navigation=False,
        network_mode="public_web_only",
    )


def packet_from_browser_observations(
    *,
    request: InternetScoutRequest,
    observations: list[BrowserRunObservation],
) -> InternetEvidencePacket:
    sources = [
        build_source_reference(
            url=observation.url,
            title=observation.title,
            content=observation.visible_text,
            fetched_at=observation.fetched_at,
        )
        for observation in observations
    ]
    claims: list[EvidenceClaim] = []
    for source, observation in zip(sources, observations, strict=True):
        excerpt = observation.visible_text.strip()[:1000]
        if not excerpt:
            continue
        claims.append(
            EvidenceClaim(
                claim=excerpt[:2000],
                source_url=source.url,
                citation_text=excerpt,
                confidence="medium",
            )
        )
    return build_evidence_packet(request=request, sources=sources, claims=claims)


def _validate_observations(
    observations: list[BrowserRunObservation],
    sandbox: BrowserSandboxPolicy,
) -> None:
    if not observations:
        raise HTTPException(status_code=502, detail="browser_no_observations")
    for observation in observations:
        if observation.host not in sandbox.allowed_hosts:
            raise HTTPException(
                status_code=502,
                detail="browser_cross_host_observation_blocked",
            )
        if sandbox.require_screenshot and not observation.screenshot_ref:
            raise HTTPException(status_code=502, detail="browser_screenshot_missing")
