#!/usr/bin/env python3
"""Smoke Alpha MVP external-data wiring without printing secrets."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import ssl
import sys
import urllib.error
from urllib.parse import urlencode
import urllib.request
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "common", REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DEFAULT_BRAIN_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_GATEWAY_BASE_URL = "https://jarvis-gateway.tail40ed36.ts.net:8283"
DEFAULT_ENDPOINT_BASE_URL = "https://jarvis-endpoint.tail40ed36.ts.net:4100"
DEFAULT_SANDBOX_BASE_URL = "https://jarvis-sandbox.tail40ed36.ts.net:5001"
DEFAULT_SMOKE_WEATHER_LATITUDE = 40.7128
DEFAULT_SMOKE_WEATHER_LONGITUDE = -74.0060
REQUIRED_SOURCE_IDS = ("open-meteo", "brave-search", "perplexity-search")
SECRET_KEYS = ("GATEWAY_TOKEN", "ALPHA_SERVICE_TOKEN", "ALPHA_BRAIN_SERVICE_TOKEN")


@dataclass(frozen=True)
class SmokeResult:
    status: str
    detail: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry-root",
        default=os.getenv("JARVIS_DATA_SOURCES_ROOT"),
        help="Path to jarvis-data-sources root or registry directory.",
    )
    parser.add_argument("--live", action="store_true", help="Probe deployed services.")
    parser.add_argument(
        "--require-gateway-token",
        action="store_true",
        help="Fail live mode when no Gateway bearer token is available.",
    )
    parser.add_argument(
        "--brain-base-url",
        default=os.getenv("ALPHA_BRAIN_BASE_URL", DEFAULT_BRAIN_BASE_URL),
    )
    parser.add_argument(
        "--gateway-base-url",
        default=os.getenv("ALPHA_GATEWAY_BASE_URL", DEFAULT_GATEWAY_BASE_URL),
    )
    parser.add_argument(
        "--endpoint-base-url",
        default=os.getenv("ALPHA_ENDPOINT_BASE_URL", DEFAULT_ENDPOINT_BASE_URL),
    )
    parser.add_argument(
        "--sandbox-base-url",
        default=os.getenv("ALPHA_SANDBOX_BASE_URL", DEFAULT_SANDBOX_BASE_URL),
    )
    parser.add_argument(
        "--weather-latitude",
        type=float,
        default=float(
            os.getenv("ALPHA_SMOKE_WEATHER_LATITUDE", DEFAULT_SMOKE_WEATHER_LATITUDE)
        ),
    )
    parser.add_argument(
        "--weather-longitude",
        type=float,
        default=float(
            os.getenv("ALPHA_SMOKE_WEATHER_LONGITUDE", DEFAULT_SMOKE_WEATHER_LONGITUDE)
        ),
    )
    args = parser.parse_args()

    results = {
        "registry_coverage": _registry_coverage(args.registry_root),
        "weather_current": _weather_current_contract(),
        "beacon_sources": _beacon_sources_contract(),
        "approval_egress_guardrails": _approval_egress_guardrails(),
    }
    if args.live:
        results["live"] = _live_checks(
            brain_base_url=args.brain_base_url,
            gateway_base_url=args.gateway_base_url,
            endpoint_base_url=args.endpoint_base_url,
            sandbox_base_url=args.sandbox_base_url,
            weather_latitude=args.weather_latitude,
            weather_longitude=args.weather_longitude,
            require_gateway_token=args.require_gateway_token,
        )

    failures = [
        name
        for name, result in results.items()
        if isinstance(result, SmokeResult) and result.status != "passed"
    ]
    status = "passed" if not failures else "failed"
    _emit(
        {
            "status": status,
            "checks": {name: asdict(result) for name, result in results.items()},
        }
    )
    return 0 if status == "passed" else 2


def _registry_coverage(registry_root: str | None) -> SmokeResult:
    from brain.registry.catalog import INITIAL_SKILLS
    from brain.registry.data_sources import (
        assert_skill_data_source_coverage,
        load_data_source_registry,
    )

    data_sources = load_data_source_registry(registry_root)
    assert_skill_data_source_coverage(INITIAL_SKILLS, data_sources)

    missing = [
        source_id for source_id in REQUIRED_SOURCE_IDS if source_id not in data_sources
    ]
    if missing:
        return SmokeResult("failed", {"missing_source_ids": missing})

    return SmokeResult(
        "passed",
        {
            "source_ids": list(REQUIRED_SOURCE_IDS),
            "domains": {
                source_id: data_sources[source_id].domain
                for source_id in REQUIRED_SOURCE_IDS
            },
        },
    )


def _weather_current_contract() -> SmokeResult:
    from brain.registry.catalog import INITIAL_SKILLS
    from brain.registry.models import SkillManifestV1

    skill = _skill_by_name("weather.current", INITIAL_SKILLS)
    manifest = SkillManifestV1.model_validate(skill.metadata["manifest"])
    expected = (
        skill.status == "active"
        and skill.approval_tier == "T1"
        and manifest.side_effect_class == "read"
        and manifest.egress.mode == "gateway"
        and manifest.egress.provider == "open_meteo"
        and manifest.egress.data_source_id == "open-meteo"
    )
    return SmokeResult(
        "passed" if expected else "failed",
        {
            "status": skill.status,
            "approval_tier": skill.approval_tier,
            "egress_mode": manifest.egress.mode,
            "provider": manifest.egress.provider,
            "data_source_id": manifest.egress.data_source_id,
        },
    )


def _beacon_sources_contract() -> SmokeResult:
    from brain.registry.catalog import INITIAL_SKILLS
    from brain.registry.models import SkillManifestV1

    detail: dict[str, Any] = {}
    ok = True
    for skill_name, approval_tier in (
        ("internet_scout.search", "T2"),
        ("internet_scout.deep_research", "T3"),
    ):
        skill = _skill_by_name(skill_name, INITIAL_SKILLS)
        manifest = SkillManifestV1.model_validate(skill.metadata["manifest"])
        source_ids = sorted(manifest.egress.data_source_ids)
        skill_ok = (
            skill.status == "active"
            and skill.approval_tier == approval_tier
            and manifest.side_effect_class == "read"
            and manifest.egress.mode == "gateway"
            and manifest.egress.provider == "beacon"
            and source_ids == ["brave-search", "perplexity-search"]
        )
        ok = ok and skill_ok
        detail[skill_name] = {
            "status": skill.status,
            "approval_tier": skill.approval_tier,
            "egress_mode": manifest.egress.mode,
            "provider": manifest.egress.provider,
            "data_source_ids": source_ids,
        }
    return SmokeResult("passed" if ok else "failed", detail)


def _approval_egress_guardrails() -> SmokeResult:
    from brain.registry.catalog import INITIAL_AGENTS, INITIAL_SKILLS
    from brain.registry.models import SkillManifestV1
    from brain.skills.policy_gate import SkillInvocation, SkillPolicyGate

    agents = {agent.agent_id: agent for agent in INITIAL_AGENTS}
    skills = {skill.name: skill for skill in INITIAL_SKILLS}
    gate = SkillPolicyGate()
    agent = agents["internet_scout"]
    search_skill = skills["internet_scout.search"]
    browser_skill = skills["internet_scout.browser_task"]
    browser_manifest = SkillManifestV1.model_validate(
        browser_skill.metadata["manifest"]
    )

    search_decision = gate.evaluate_rows(
        invocation=SkillInvocation(
            agent_id="internet_scout",
            skill_name="internet_scout.search",
            estimated_cost_usd=Decimal("0.01"),
        ),
        agent_row=_agent_row(agent),
        skill_row=_skill_row(search_skill),
        spent_today_usd=Decimal("0"),
    )
    browser_decision = gate.evaluate_rows(
        invocation=SkillInvocation(
            agent_id="internet_scout",
            skill_name="internet_scout.browser_task",
            idempotency_key="mvp-smoke-browser-task",
            estimated_cost_usd=Decimal("0.01"),
        ),
        agent_row=_agent_row(agent),
        skill_row=_skill_row(browser_skill),
        spent_today_usd=Decimal("0"),
    )
    ok = (
        search_decision.allowed
        and browser_decision.requires_approval
        and browser_decision.reason == "t4_approval_required"
        and browser_manifest.egress.mode == "gateway"
        and browser_manifest.egress.provider == "beacon_browser_runtime"
    )
    return SmokeResult(
        "passed" if ok else "failed",
        {
            "search_decision": search_decision.outcome,
            "search_reason": search_decision.reason,
            "browser_task_decision": browser_decision.outcome,
            "browser_task_reason": browser_decision.reason,
            "browser_task_egress_mode": browser_manifest.egress.mode,
            "browser_task_provider": browser_manifest.egress.provider,
        },
    )


def _live_checks(
    *,
    brain_base_url: str,
    gateway_base_url: str,
    endpoint_base_url: str,
    sandbox_base_url: str,
    weather_latitude: float,
    weather_longitude: float,
    require_gateway_token: bool,
) -> SmokeResult:
    detail: dict[str, Any] = {
        "service_health": {
            "brain": _health_get(brain_base_url, "/health"),
            "gateway": _health_get(gateway_base_url, "/health"),
            "endpoint": _health_get(endpoint_base_url, "/health"),
            "sandbox": _health_get(sandbox_base_url, "/health"),
        }
    }
    token = _gateway_token()
    if token is None:
        detail["gateway_token_gated"] = {
            "status": "failed" if require_gateway_token else "skipped",
            "reason": "gateway token not available",
        }
    else:
        detail["weather_current"] = _json_request(
            "GET",
            gateway_base_url,
            _weather_current_path(
                latitude=weather_latitude,
                longitude=weather_longitude,
            ),
            token=token,
        )
        detail["beacon_provider_health"] = _json_request(
            "POST",
            gateway_base_url,
            "/v1/cloud/internet/health",
            token=token,
        )

    status = (
        "passed" if _live_detail_passed(detail, require_gateway_token) else "failed"
    )
    return SmokeResult(status, detail)


def _weather_current_path(*, latitude: float, longitude: float) -> str:
    params = urlencode(
        {
            "latitude": f"{latitude:.6f}",
            "longitude": f"{longitude:.6f}",
            "location_label": "mvp-smoke",
        }
    )
    return f"/v1/weather/current?{params}"


def _skill_by_name(skill_name: str, skills: tuple[Any, ...]) -> Any:
    for skill in skills:
        if skill.name == skill_name:
            return skill
    raise AssertionError(f"missing skill {skill_name}")


def _agent_row(agent: Any) -> dict[str, Any]:
    return {
        "agent_id": agent.agent_id,
        "status": agent.status,
        "enabled": agent.enabled,
        "allowed_skills": agent.allowed_skills,
        "allowed_scopes": agent.allowed_scopes,
        "cost_daily_cap_usd": (
            Decimal(str(agent.cost_daily_cap_usd))
            if agent.cost_daily_cap_usd is not None
            else Decimal("0.50")
        ),
    }


def _skill_row(skill: Any) -> dict[str, Any]:
    return {
        "skill_name": skill.name,
        "domain": skill.domain,
        "approval_tier": skill.approval_tier,
        "scope": skill.scope,
        "status": skill.status,
        "mutates_state": skill.mutates_state,
        "body_access": skill.body_access,
        "idempotency_required": skill.idempotency_required,
        "metadata": skill.metadata,
    }


def _gateway_token() -> str | None:
    for name in SECRET_KEYS:
        value = os.getenv(name)
        if value:
            return value
    file_token = _gateway_token_from_secret_files()
    if file_token:
        return file_token
    try:
        from jarvis_common.secrets import get_secret
    except Exception:
        return None
    for name in SECRET_KEYS:
        try:
            value = get_secret(name).strip()
        except KeyError:
            continue
        if value:
            return value
    return None


def _gateway_token_from_secret_files() -> str | None:
    paths: list[Path] = []
    configured = os.getenv("SECRETS_FILE")
    if configured:
        paths.append(Path(configured).expanduser())
    paths.extend([Path.home() / ".secrets", Path.home() / "jarvis" / ".secrets"])

    for path in dict.fromkeys(paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() in SECRET_KEYS and value.strip():
                return value.strip().strip("'\"")
    return None


def _health_get(base_url: str, path: str) -> dict[str, Any]:
    return _json_request("GET", base_url, path, token=None)


def _json_request(
    method: str,
    base_url: str,
    path: str,
    *,
    token: str | None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
            context=ssl._create_unverified_context(),
        ) as response:
            raw = response.read().decode("utf-8")
        try:
            payload: Any = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = None
        return {
            "status": "passed",
            "http_status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "payload_status": payload.get("status")
            if isinstance(payload, dict)
            else None,
            "body_type": "json" if isinstance(payload, dict) else "text",
            "summary": _live_payload_summary(payload),
        }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        return {"status": "failed", "http_status": exc.code, "error": body}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


def _live_payload_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    keys = (
        "node",
        "mode",
        "provider",
        "configured_provider_count",
        "usable_provider_count",
        "provider_redundancy_status",
        "provider_warning_status",
        "primary_provider",
        "primary_provider_usable",
        "budget_capped_backup_provider_count",
    )
    summary = {key: payload[key] for key in keys if key in payload}
    providers = payload.get("providers")
    if isinstance(providers, list):
        summary["providers"] = [
            {
                "provider": provider.get("provider"),
                "data_source_id": provider.get("data_source_id"),
                "configured": provider.get("configured"),
                "budget_exhausted": provider.get("budget_exhausted"),
                "circuit_open": provider.get("circuit_open"),
            }
            for provider in providers
            if isinstance(provider, dict)
        ]
    return summary


def _live_detail_passed(detail: dict[str, Any], require_gateway_token: bool) -> bool:
    service_health = detail.get("service_health")
    if not isinstance(service_health, dict):
        return False
    if any(item.get("status") != "passed" for item in service_health.values()):
        return False

    gated = detail.get("gateway_token_gated")
    if isinstance(gated, dict):
        return not require_gateway_token and gated.get("status") == "skipped"

    weather = detail.get("weather_current")
    provider = detail.get("beacon_provider_health")
    return (
        isinstance(weather, dict)
        and weather.get("status") == "passed"
        and isinstance(provider, dict)
        and provider.get("status") == "passed"
    )


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
