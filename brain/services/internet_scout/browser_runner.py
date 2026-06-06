"""Approval-gated Beacon browser task runner contracts."""

from __future__ import annotations

import hashlib
from importlib import import_module, metadata
import os
from pathlib import Path
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
from brain.services.internet_scout.sanitizer import sanitize_untrusted_text

EXPECTED_PLAYWRIGHT_VERSION = "1.49.1"
DEFAULT_BROWSER_RUNS_PER_HOUR = 3
DEFAULT_BROWSER_TIMEOUT_MS = 20_000


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
    def __init__(self, reason: str = "browser_runtime_not_configured") -> None:
        self.reason = reason

    async def run(
        self,
        *,
        request: InternetScoutRequest,
        sandbox: BrowserSandboxPolicy,
    ) -> list[BrowserRunObservation]:
        raise BrowserRuntimeUnavailableError(self.reason)


class BrowserScreenshotStore:
    """Content-addressed screenshot store for reviewed browser observations."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save_png(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{digest}.png"
        if not path.exists():
            path.write_bytes(data)
        return f"sha256:{digest}"


class PlaywrightBrowserTaskAdapter:
    """Production browser adapter for public, read-only page observation."""

    def __init__(
        self,
        *,
        screenshot_store: BrowserScreenshotStore,
        timeout_ms: int = DEFAULT_BROWSER_TIMEOUT_MS,
    ) -> None:
        self.screenshot_store = screenshot_store
        self.timeout_ms = timeout_ms

    @classmethod
    def from_env(cls) -> "PlaywrightBrowserTaskAdapter":
        screenshot_dir = os.getenv("BEACON_BROWSER_SCREENSHOT_DIR", "").strip()
        if not screenshot_dir:
            raise BrowserRuntimeUnavailableError(
                "browser_screenshot_dir_not_configured"
            )
        _require_playwright_version()
        timeout_ms = _bounded_int_env(
            "BEACON_BROWSER_TIMEOUT_MS",
            default=DEFAULT_BROWSER_TIMEOUT_MS,
            minimum=5_000,
            maximum=60_000,
        )
        return cls(
            screenshot_store=BrowserScreenshotStore(Path(screenshot_dir)),
            timeout_ms=timeout_ms,
        )

    async def run(
        self,
        *,
        request: InternetScoutRequest,
        sandbox: BrowserSandboxPolicy,
    ) -> list[BrowserRunObservation]:
        if not request.urls:
            raise BrowserSandboxPolicyError("browser_start_url_required")

        module = import_module("playwright.async_api")
        async_playwright = getattr(module, "async_playwright")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    accept_downloads=False,
                    ignore_https_errors=False,
                )
                page = await context.new_page()
                await page.goto(
                    request.urls[0],
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
                final_url = str(page.url)
                final_safety = validate_url(final_url)
                if (
                    not final_safety.allowed
                    or final_safety.host not in sandbox.allowed_hosts
                ):
                    raise BrowserSandboxPolicyError(
                        "browser_cross_host_navigation_blocked"
                    )
                title = await page.title()
                raw_visible_text = await page.locator("body").inner_text(
                    timeout=self.timeout_ms
                )
                sanitized = sanitize_untrusted_text(raw_visible_text, max_chars=5000)
                screenshot = await page.screenshot(full_page=True)
                screenshot_ref = self.screenshot_store.save_png(screenshot)
                content_hash = hashlib.sha256(
                    sanitized.text.encode("utf-8")
                ).hexdigest()
                return [
                    BrowserRunObservation(
                        url=final_safety.normalized_url or final_url,
                        host=final_safety.host or "",
                        title=title,
                        visible_text=sanitized.text,
                        screenshot_ref=screenshot_ref,
                        content_hash=content_hash,
                        risk_markers=sanitized.risk_markers,
                    )
                ]
            finally:
                await browser.close()


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


def build_browser_task_runner_from_env() -> BrowserTaskRunner:
    runtime = os.getenv("BEACON_BROWSER_RUNTIME", "").strip().lower()
    if runtime in {"", "disabled", "off"}:
        return BrowserTaskRunner()
    if runtime != "playwright":
        return BrowserTaskRunner(
            adapter=DisabledBrowserTaskAdapter("browser_runtime_not_supported")
        )
    try:
        adapter = PlaywrightBrowserTaskAdapter.from_env()
    except BrowserRuntimeUnavailableError as exc:
        return BrowserTaskRunner(adapter=DisabledBrowserTaskAdapter(str(exc)))
    return BrowserTaskRunner(adapter=adapter)


def browser_hourly_run_limit() -> int:
    return _bounded_int_env(
        "BEACON_BROWSER_MAX_RUNS_PER_HOUR",
        default=DEFAULT_BROWSER_RUNS_PER_HOUR,
        minimum=1,
        maximum=10,
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


def _require_playwright_version() -> None:
    expected = os.getenv(
        "BEACON_BROWSER_PLAYWRIGHT_VERSION",
        EXPECTED_PLAYWRIGHT_VERSION,
    ).strip()
    try:
        actual = metadata.version("playwright")
    except metadata.PackageNotFoundError as exc:
        raise BrowserRuntimeUnavailableError(
            "browser_playwright_not_installed"
        ) from exc
    if actual != expected:
        raise BrowserRuntimeUnavailableError("browser_playwright_version_mismatch")


def _bounded_int_env(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return min(max(parsed, minimum), maximum)
