"""Approval-gated Beacon browser task runner contracts."""

from __future__ import annotations

import hashlib
from importlib import import_module, metadata
import os
from pathlib import Path
from time import perf_counter
from typing import Awaitable, Callable, Protocol
from uuid import UUID

from fastapi import HTTPException

from brain.services.internet_scout.evidence import (
    build_evidence_packet,
    build_source_reference,
)
from brain.services.internet_scout.models import (
    BrowserActionAuditEvent,
    BrowserClickTarget,
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
DEFAULT_BROWSER_MAX_STEPS = 5

BrowserActionAuditCallback = Callable[[BrowserActionAuditEvent], Awaitable[None]]


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
        audit_action: BrowserActionAuditCallback | None = None,
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
        audit_action: BrowserActionAuditCallback | None = None,
    ) -> list[BrowserRunObservation]:
        await _emit_action(
            audit_action,
            BrowserActionAuditEvent(
                sequence=0,
                action="runtime",
                status="failed",
                blocked_reason=self.reason,
            ),
        )
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
    """Production browser adapter for approved public-page observation/clicks."""

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
        audit_action: BrowserActionAuditCallback | None = None,
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
                await context.route(
                    "**/*",
                    lambda route: _enforce_browser_request_allowlist(
                        route,
                        allowed_hosts=set(sandbox.allowed_hosts),
                    ),
                )
                page = await context.new_page()
                page.set_default_timeout(self.timeout_ms)
                sequence = 1
                await _timed_action(
                    audit_action,
                    action="navigate",
                    sequence=sequence,
                    host=sandbox.allowed_hosts[0],
                    url_hash=_hash_url(request.urls[0]),
                    operation=lambda: page.goto(
                        request.urls[0],
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    ),
                )
                sequence += 1
                final_url = str(page.url)
                final_safety = validate_url(final_url)
                if (
                    not final_safety.allowed
                    or final_safety.host not in sandbox.allowed_hosts
                ):
                    await _emit_action(
                        audit_action,
                        BrowserActionAuditEvent(
                            sequence=sequence,
                            action="navigate",
                            status="blocked",
                            host=final_safety.host,
                            url_hash=_hash_url(final_url),
                            blocked_reason="browser_cross_host_navigation_blocked",
                        ),
                    )
                    raise BrowserSandboxPolicyError(
                        "browser_cross_host_navigation_blocked"
                    )
                await _timed_action(
                    audit_action,
                    action="inspect_controls",
                    sequence=sequence,
                    host=final_safety.host,
                    url_hash=_hash_url(final_url),
                    operation=lambda: _assert_no_disallowed_form_controls(page),
                )
                sequence += 1
                for click_index, click in enumerate(request.browser_clicks, start=1):
                    before_ref = await _capture_review_screenshot(
                        page,
                        store=self.screenshot_store,
                        audit_action=audit_action,
                        sequence=sequence,
                        host=final_safety.host,
                        url_hash=_hash_url(final_url),
                        phase="before_click",
                        click_index=click_index,
                    )
                    sequence += 1
                    snapshot = await _approved_click_target_snapshot(
                        page,
                        click=click,
                        sandbox=sandbox,
                    )
                    await _timed_action(
                        audit_action,
                        action="click",
                        sequence=sequence,
                        host=final_safety.host,
                        url_hash=_hash_url(final_url),
                        metadata={
                            "click_index": click_index,
                            "before_screenshot_ref": before_ref,
                            "target_tag": snapshot.get("tag"),
                            "target_role": snapshot.get("role"),
                            "target_href_hash": _hash_url(str(snapshot["href"]))
                            if snapshot.get("href")
                            else None,
                        },
                        operation=lambda click=click: _first_locator(
                            page, click.selector
                        ).click(timeout=self.timeout_ms),
                    )
                    sequence += 1
                    final_url = str(page.url)
                    final_safety = validate_url(final_url)
                    if (
                        not final_safety.allowed
                        or final_safety.host not in sandbox.allowed_hosts
                    ):
                        await _emit_action(
                            audit_action,
                            BrowserActionAuditEvent(
                                sequence=sequence,
                                action="click",
                                status="blocked",
                                host=final_safety.host,
                                url_hash=_hash_url(final_url),
                                blocked_reason="browser_click_cross_host_blocked",
                            ),
                        )
                        raise BrowserSandboxPolicyError(
                            "browser_click_cross_host_blocked"
                        )
                    await _timed_action(
                        audit_action,
                        action="inspect_controls",
                        sequence=sequence,
                        host=final_safety.host,
                        url_hash=_hash_url(final_url),
                        metadata={"click_index": click_index},
                        operation=lambda: _assert_no_disallowed_form_controls(page),
                    )
                    sequence += 1
                    await _capture_review_screenshot(
                        page,
                        store=self.screenshot_store,
                        audit_action=audit_action,
                        sequence=sequence,
                        host=final_safety.host,
                        url_hash=_hash_url(final_url),
                        phase="after_click",
                        click_index=click_index,
                    )
                    sequence += 1
                title = await page.title()
                raw_visible_text = await _timed_action(
                    audit_action,
                    action="extract_text",
                    sequence=sequence,
                    host=final_safety.host,
                    url_hash=_hash_url(final_url),
                    operation=lambda: page.locator("body").inner_text(
                        timeout=self.timeout_ms
                    ),
                )
                sequence += 1
                sanitized = sanitize_untrusted_text(raw_visible_text, max_chars=5000)
                screenshot_ref = await _capture_review_screenshot(
                    page,
                    store=self.screenshot_store,
                    audit_action=audit_action,
                    sequence=sequence,
                    host=final_safety.host,
                    url_hash=_hash_url(final_url),
                    phase="final_observation",
                )
                sequence += 1
                content_hash = hashlib.sha256(
                    sanitized.text.encode("utf-8")
                ).hexdigest()
                await _emit_action(
                    audit_action,
                    BrowserActionAuditEvent(
                        sequence=sequence,
                        action="observe",
                        status="succeeded",
                        host=final_safety.host,
                        url_hash=_hash_url(final_url),
                        content_hash=content_hash,
                        screenshot_ref=screenshot_ref,
                        metadata={"risk_marker_count": len(sanitized.risk_markers)},
                    ),
                )
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
        audit_action: BrowserActionAuditCallback | None = None,
    ) -> InternetScoutBrowserRunResponse:
        action_audit: list[BrowserActionAuditEvent] = []

        async def record_action(event: BrowserActionAuditEvent) -> None:
            action_audit.append(event)
            if audit_action is not None:
                await audit_action(event)

        await _emit_action(
            record_action,
            BrowserActionAuditEvent(
                sequence=0,
                action="sandbox",
                status="started",
                metadata={
                    "requested_max_steps": max_steps,
                    "require_screenshot": require_screenshot,
                },
            ),
        )
        try:
            sandbox = build_browser_sandbox_policy(
                request,
                max_steps=max_steps,
                require_screenshot=require_screenshot,
            )
        except BrowserSandboxPolicyError as exc:
            await _emit_action(
                record_action,
                BrowserActionAuditEvent(
                    sequence=1,
                    action="sandbox",
                    status="blocked",
                    blocked_reason=str(exc),
                ),
            )
            raise
        await _emit_action(
            record_action,
            BrowserActionAuditEvent(
                sequence=1,
                action="sandbox",
                status="succeeded",
                metadata={
                    "allowed_host_count": len(sandbox.allowed_hosts),
                    "max_steps": sandbox.max_steps,
                    "allow_downloads": sandbox.allow_downloads,
                    "allow_forms": sandbox.allow_forms,
                    "allow_cross_host_navigation": sandbox.allow_cross_host_navigation,
                    "network_mode": sandbox.network_mode,
                },
            ),
        )
        observations = await self.adapter.run(
            request=request,
            sandbox=sandbox,
            audit_action=record_action,
        )
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
            action_audit=action_audit,
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


def browser_max_steps_limit() -> int:
    return _bounded_int_env(
        "BEACON_BROWSER_MAX_STEPS",
        default=DEFAULT_BROWSER_MAX_STEPS,
        minimum=1,
        maximum=DEFAULT_BROWSER_MAX_STEPS,
    )


def browser_runtime_health() -> dict[str, object]:
    runtime = os.getenv("BEACON_BROWSER_RUNTIME", "").strip().lower()
    screenshot_dir = os.getenv("BEACON_BROWSER_SCREENSHOT_DIR", "").strip()
    installed_version = _installed_playwright_version()
    runtime_enabled = runtime not in {"", "disabled", "off"}
    runtime_supported = runtime in {"", "disabled", "off", "playwright"}
    version_ok = installed_version == EXPECTED_PLAYWRIGHT_VERSION
    screenshot_path = Path(screenshot_dir) if screenshot_dir else None
    screenshot_dir_exists = (
        screenshot_path.exists() and screenshot_path.is_dir()
        if screenshot_path is not None
        else False
    )
    screenshot_dir_writable = (
        os.access(screenshot_path, os.W_OK)
        if screenshot_path is not None and screenshot_dir_exists
        else False
    )
    ok = (
        runtime_enabled
        and runtime == "playwright"
        and version_ok
        and screenshot_dir_exists
        and screenshot_dir_writable
    )
    return {
        "ok": ok,
        "runtime": runtime or "disabled",
        "runtime_enabled": runtime_enabled,
        "runtime_supported": runtime_supported,
        "expected_playwright_version": EXPECTED_PLAYWRIGHT_VERSION,
        "installed_playwright_version": installed_version,
        "playwright_version_ok": version_ok,
        "screenshot_dir_configured": bool(screenshot_dir),
        "screenshot_dir_exists": screenshot_dir_exists,
        "screenshot_dir_writable": screenshot_dir_writable,
        "timeout_ms": _bounded_int_env(
            "BEACON_BROWSER_TIMEOUT_MS",
            default=DEFAULT_BROWSER_TIMEOUT_MS,
            minimum=5_000,
            maximum=60_000,
        ),
        "max_steps": browser_max_steps_limit(),
        "max_runs_per_hour": browser_hourly_run_limit(),
    }


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
    max_allowed_steps = browser_max_steps_limit()
    if max_steps > max_allowed_steps:
        raise BrowserSandboxPolicyError("browser_max_steps_exceeded")
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
    first_host: str | None = None
    for url in normalized.urls:
        safety = validate_url(url)
        if not safety.allowed or safety.host is None:
            raise BrowserSandboxPolicyError("browser_start_url_not_public")
        if first_host is None:
            first_host = safety.host
        elif safety.host != first_host:
            raise BrowserSandboxPolicyError("browser_start_urls_must_share_host")
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


async def _emit_action(
    audit_action: BrowserActionAuditCallback | None,
    event: BrowserActionAuditEvent,
) -> None:
    if audit_action is not None:
        await audit_action(event)


async def _timed_action(
    audit_action: BrowserActionAuditCallback | None,
    *,
    action: str,
    sequence: int,
    host: str | None,
    url_hash: str | None,
    operation,
    metadata: dict[str, object] | None = None,
):
    started = perf_counter()
    await _emit_action(
        audit_action,
        BrowserActionAuditEvent(
            sequence=sequence,
            action=action,
            status="started",
            host=host,
            url_hash=url_hash,
            metadata=metadata or {},
        ),
    )
    try:
        result = await operation()
    except BrowserSandboxPolicyError as exc:
        await _emit_action(
            audit_action,
            BrowserActionAuditEvent(
                sequence=sequence,
                action=action,
                status="blocked",
                host=host,
                url_hash=url_hash,
                elapsed_ms=_elapsed_ms(started),
                blocked_reason=str(exc),
                metadata=metadata or {},
            ),
        )
        raise
    except Exception as exc:
        await _emit_action(
            audit_action,
            BrowserActionAuditEvent(
                sequence=sequence,
                action=action,
                status="failed",
                host=host,
                url_hash=url_hash,
                elapsed_ms=_elapsed_ms(started),
                blocked_reason=exc.__class__.__name__,
                metadata=metadata or {},
            ),
        )
        raise
    await _emit_action(
        audit_action,
        BrowserActionAuditEvent(
            sequence=sequence,
            action=action,
            status="succeeded",
            host=host,
            url_hash=url_hash,
            elapsed_ms=_elapsed_ms(started),
            metadata=metadata or {},
        ),
    )
    return result


async def _capture_review_screenshot(
    page,
    *,
    store: BrowserScreenshotStore,
    audit_action: BrowserActionAuditCallback | None,
    sequence: int,
    host: str | None,
    url_hash: str | None,
    phase: str,
    click_index: int | None = None,
) -> str:
    started = perf_counter()
    metadata = {"phase": phase}
    if click_index is not None:
        metadata["click_index"] = click_index
    await _emit_action(
        audit_action,
        BrowserActionAuditEvent(
            sequence=sequence,
            action="screenshot",
            status="started",
            host=host,
            url_hash=url_hash,
            metadata=metadata,
        ),
    )
    try:
        data = await page.screenshot(full_page=True)
    except Exception as exc:
        await _emit_action(
            audit_action,
            BrowserActionAuditEvent(
                sequence=sequence,
                action="screenshot",
                status="failed",
                host=host,
                url_hash=url_hash,
                elapsed_ms=_elapsed_ms(started),
                blocked_reason=exc.__class__.__name__,
                metadata=metadata,
            ),
        )
        raise
    screenshot_ref = store.save_png(data)
    await _emit_action(
        audit_action,
        BrowserActionAuditEvent(
            sequence=sequence,
            action="screenshot",
            status="succeeded",
            host=host,
            url_hash=url_hash,
            elapsed_ms=_elapsed_ms(started),
            screenshot_ref=screenshot_ref,
            metadata=metadata,
        ),
    )
    return screenshot_ref


async def _enforce_browser_request_allowlist(route, *, allowed_hosts: set[str]) -> None:
    request = route.request
    url = str(request.url)
    safety = validate_url(url)
    if not safety.allowed or safety.host not in allowed_hosts:
        await route.abort("blockedbyclient")
        return
    await route.continue_()


async def _assert_no_disallowed_form_controls(page) -> None:
    controls = await page.evaluate(
        """
        () => Array.from(
          document.querySelectorAll('form,input,textarea,select,[contenteditable="true"]')
        ).slice(0, 50).map((el) => ({
          tag: String(el.tagName || '').toLowerCase(),
          type: String(el.getAttribute('type') || '').toLowerCase(),
          name: String(el.getAttribute('name') || '').toLowerCase(),
          id: String(el.getAttribute('id') || '').toLowerCase(),
          autocomplete: String(el.getAttribute('autocomplete') || '').toLowerCase(),
          placeholder: String(el.getAttribute('placeholder') || '').toLowerCase(),
          contentEditable: String(el.getAttribute('contenteditable') || '').toLowerCase()
        }))
        """
    )
    reason = classify_disallowed_browser_controls(controls)
    if reason is not None:
        raise BrowserSandboxPolicyError(reason)


async def _approved_click_target_snapshot(
    page,
    *,
    click: BrowserClickTarget,
    sandbox: BrowserSandboxPolicy,
) -> dict[str, object]:
    locator = _first_locator(page, click.selector)
    try:
        await locator.wait_for(state="visible")
        snapshot = await locator.evaluate(
            """
            (el) => ({
              tag: String(el.tagName || '').toLowerCase(),
              type: String(el.getAttribute('type') || '').toLowerCase(),
              role: String(el.getAttribute('role') || '').toLowerCase(),
              name: String(el.getAttribute('name') || '').toLowerCase(),
              id: String(el.getAttribute('id') || '').toLowerCase(),
              ariaLabel: String(el.getAttribute('aria-label') || '').toLowerCase(),
              text: String(el.innerText || el.textContent || '').toLowerCase().slice(0, 200),
              href: String(el.href || el.getAttribute('href') || ''),
              contentEditable: String(el.getAttribute('contenteditable') || '').toLowerCase()
            })
            """
        )
    except Exception as exc:
        raise BrowserSandboxPolicyError("browser_click_target_not_found") from exc
    reason = classify_disallowed_browser_click_target(
        snapshot,
        allowed_hosts=sandbox.allowed_hosts,
        expected_host=click.expected_host,
    )
    if reason is not None:
        raise BrowserSandboxPolicyError(reason)
    return snapshot


def _first_locator(page, selector: str):
    locator = page.locator(selector)
    first = getattr(locator, "first", None)
    if first is None:
        return locator
    return first() if callable(first) else first


def classify_disallowed_browser_controls(controls: object) -> str | None:
    if not isinstance(controls, list) or not controls:
        return None
    credential_markers = {
        "password",
        "passwd",
        "passcode",
        "otp",
        "token",
        "email",
        "username",
        "login",
        "tel",
        "phone",
        "card",
        "cc",
        "credit",
        "ssn",
    }
    for control in controls:
        if not isinstance(control, dict):
            return "browser_forms_blocked"
        haystack = " ".join(
            str(control.get(key, "")).lower()
            for key in (
                "tag",
                "type",
                "name",
                "id",
                "autocomplete",
                "placeholder",
                "contentEditable",
            )
        )
        if any(marker in haystack for marker in credential_markers):
            return "browser_credential_fields_blocked"
    return "browser_forms_blocked"


def classify_disallowed_browser_click_target(
    target: object,
    *,
    allowed_hosts: list[str],
    expected_host: str | None = None,
) -> str | None:
    if not isinstance(target, dict):
        return "browser_click_target_invalid"
    tag = str(target.get("tag", "")).lower()
    if tag in {"form", "input", "textarea", "select", "option"}:
        return "browser_click_form_control_blocked"
    if str(target.get("contentEditable", "")).lower() == "true":
        return "browser_click_form_control_blocked"

    href = str(target.get("href", "")).strip()
    if href:
        safety = validate_url(href)
        if not safety.allowed or safety.host not in allowed_hosts:
            return "browser_click_cross_host_blocked"
        if expected_host and safety.host != expected_host:
            return "browser_click_unexpected_host_blocked"
    elif expected_host:
        return "browser_click_expected_host_missing"

    haystack = " ".join(
        str(target.get(key, "")).lower()
        for key in ("type", "role", "name", "id", "ariaLabel", "text", "href")
    )
    risky_markers = {
        "buy",
        "checkout",
        "confirm",
        "credit",
        "login",
        "order",
        "password",
        "pay",
        "payment",
        "post",
        "purchase",
        "send",
        "sign in",
        "submit",
    }
    if any(marker in haystack for marker in risky_markers):
        return "browser_click_risky_target_blocked"
    return None


def _hash_url(url: str) -> str:
    return "sha256:" + hashlib.sha256(url.encode("utf-8")).hexdigest()


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


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


def _installed_playwright_version() -> str | None:
    try:
        return metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return None


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
