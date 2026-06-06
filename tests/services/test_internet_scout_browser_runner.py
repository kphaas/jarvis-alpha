from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from brain.services.internet_scout.browser_runner import (
    BrowserSandboxPolicyError,
    BrowserRuntimeUnavailableError,
    BrowserScreenshotStore,
    BrowserTaskRunner,
    browser_hourly_run_limit,
    build_browser_sandbox_policy,
    build_browser_task_runner_from_env,
)
from brain.services.internet_scout.evidence import content_hash
from brain.services.internet_scout.models import (
    BrowserRunObservation,
    BrowserSandboxPolicy,
    InternetScoutRequest,
    InternetTool,
)
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator


class FakeBrowserAdapter:
    async def run(
        self,
        *,
        request: InternetScoutRequest,
        sandbox: BrowserSandboxPolicy,
    ) -> list[BrowserRunObservation]:
        return [
            BrowserRunObservation(
                url="https://public.example.test/pricing",
                host="public.example.test",
                title="Pricing",
                visible_text="Pricing page body.",
                screenshot_ref="sha256:" + "1" * 64,
                content_hash=content_hash("Pricing page body."),
                fetched_at=datetime(2026, 6, 6, 15, 0, tzinfo=UTC),
                risk_markers=[],
            )
        ]


def test_browser_sandbox_blocks_t5_sensitive_browser_work():
    with pytest.raises(BrowserSandboxPolicyError) as exc:
        build_browser_sandbox_policy(
            InternetScoutRequest(
                urls=["https://public.example.test"],
                needs_interaction=True,
                sensitivity="privacy",
            ),
            max_steps=5,
            require_screenshot=True,
        )

    assert str(exc.value) == "browser_use_t5_deferred"


def test_browser_sandbox_requires_public_start_url():
    with pytest.raises(BrowserSandboxPolicyError) as exc:
        build_browser_sandbox_policy(
            InternetScoutRequest(
                urls=["http://127.0.0.1:8000/admin"],
                needs_interaction=True,
            ),
            max_steps=5,
            require_screenshot=True,
        )

    assert str(exc.value) == "browser_start_url_not_public"


def test_browser_screenshot_store_writes_content_addressed_png(tmp_path):
    store = BrowserScreenshotStore(tmp_path)
    data = b"\x89PNG\r\n\x1a\nbeacon"

    ref = store.save_png(data)

    assert ref.startswith("sha256:")
    assert (tmp_path / f"{ref.removeprefix('sha256:')}.png").read_bytes() == data


def test_browser_hourly_run_limit_is_bounded(monkeypatch):
    monkeypatch.setenv("BEACON_BROWSER_MAX_RUNS_PER_HOUR", "999")

    assert browser_hourly_run_limit() == 10


@pytest.mark.asyncio
async def test_browser_task_runner_from_env_fails_closed_when_disabled(monkeypatch):
    monkeypatch.delenv("BEACON_BROWSER_RUNTIME", raising=False)
    runner = build_browser_task_runner_from_env()

    with pytest.raises(BrowserRuntimeUnavailableError) as exc:
        await runner.adapter.run(
            request=InternetScoutRequest(
                urls=["https://public.example.test/start"],
                needs_interaction=True,
            ),
            sandbox=BrowserSandboxPolicy(allowed_hosts=["public.example.test"]),
        )

    assert str(exc.value) == "browser_runtime_not_configured"


@pytest.mark.asyncio
async def test_browser_task_runner_from_env_reports_missing_playwright_config(
    monkeypatch,
):
    monkeypatch.setenv("BEACON_BROWSER_RUNTIME", "playwright")
    monkeypatch.delenv("BEACON_BROWSER_SCREENSHOT_DIR", raising=False)
    runner = build_browser_task_runner_from_env()

    with pytest.raises(BrowserRuntimeUnavailableError) as exc:
        await runner.adapter.run(
            request=InternetScoutRequest(
                urls=["https://public.example.test/start"],
                needs_interaction=True,
            ),
            sandbox=BrowserSandboxPolicy(allowed_hosts=["public.example.test"]),
        )

    assert str(exc.value) == "browser_screenshot_dir_not_configured"


@pytest.mark.asyncio
async def test_browser_runner_builds_evidence_from_adapter_observations():
    request = InternetScoutRequest(
        query="open pricing",
        urls=["https://public.example.test/start"],
        tool_hint=InternetTool.BROWSER_USE,
        needs_interaction=True,
    )
    plan = InternetScoutOrchestrator().plan(request)
    result = await BrowserTaskRunner(adapter=FakeBrowserAdapter()).execute(
        request_id=uuid4(),
        approval_queue_id=uuid4(),
        request=request,
        plan=plan,
        max_steps=5,
        require_screenshot=True,
    )

    assert result.status == "completed"
    assert result.sandbox.allowed_hosts == ["public.example.test"]
    assert result.observations[0].screenshot_ref == "sha256:" + "1" * 64
    assert result.evidence.claims[0].citation_text == "Pricing page body."


@pytest.mark.asyncio
async def test_browser_runner_blocks_cross_host_observation():
    class CrossHostAdapter:
        async def run(
            self,
            *,
            request: InternetScoutRequest,
            sandbox: BrowserSandboxPolicy,
        ) -> list[BrowserRunObservation]:
            return [
                BrowserRunObservation(
                    url="https://other.example.test/page",
                    host="other.example.test",
                    visible_text="Cross host.",
                    screenshot_ref="sha256:" + "2" * 64,
                    content_hash=content_hash("Cross host."),
                )
            ]

    request = InternetScoutRequest(
        urls=["https://public.example.test/start"],
        tool_hint=InternetTool.BROWSER_USE,
        needs_interaction=True,
    )
    plan = InternetScoutOrchestrator().plan(request)

    with pytest.raises(HTTPException) as exc:
        await BrowserTaskRunner(adapter=CrossHostAdapter()).execute(
            request_id=uuid4(),
            approval_queue_id=uuid4(),
            request=request,
            plan=plan,
            max_steps=5,
            require_screenshot=True,
        )

    assert exc.value.status_code == 502
    assert exc.value.detail == "browser_cross_host_observation_blocked"
