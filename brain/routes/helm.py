"""Helm read-only Alpha summary proxy."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.config.secrets import get_secret
from brain.db.rls import platform_admin_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.internet_scout.health import build_beacon_health
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/helm", tags=["helm"])
logger = get_logger("alpha_brain")

_SECURITY_AGENT_IDS = (
    "warden",
    "porchlight",
    "keyturner",
    "sweep",
    "tripwire",
    "ledger",
)
_FAMILY_HELM_SCOPE = "family.helm.read"
_HELM_ACTION_CONNECTORS = frozenset(
    {
        "alpha",
        "forge",
        "family",
        "financial",
        "medical",
        "privacy",
        "spark",
        "herald",
        "warden",
    }
)
_HELM_RISK_TIERS = {"T1", "T2", "T3", "T4", "T5"}


class RowLike(Protocol):
    def __getitem__(self, key: str) -> object: ...


class HelmApprovalSummary(BaseModel):
    pending_total: int
    by_tier: dict[str, int] = Field(default_factory=dict)
    highest_tier: str | None = None


class HelmSkillRegistrySummary(BaseModel):
    total: int
    by_status: dict[str, int] = Field(default_factory=dict)
    mutating: int
    body_access: int


class HelmAgentRegistrySummary(BaseModel):
    total: int
    enabled: int
    by_status: dict[str, int] = Field(default_factory=dict)
    by_risk_tier: dict[str, int] = Field(default_factory=dict)


class HelmRegistrySummary(BaseModel):
    skills: HelmSkillRegistrySummary
    agents: HelmAgentRegistrySummary


class HelmGatewayPosture(BaseModel):
    state: str
    active: bool


class HelmSecurityAgentSummary(BaseModel):
    total: int
    enabled: int
    by_status: dict[str, int] = Field(default_factory=dict)


class HelmPostureSummary(BaseModel):
    gateway: HelmGatewayPosture
    security_agents: HelmSecurityAgentSummary


class HelmBeaconLastRequest(BaseModel):
    id: str | None = None
    requester: str | None = None
    selected_tool: str | None = None
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class HelmBeaconSourceQualitySummary(BaseModel):
    supported: int = 0
    weak: int = 0
    insufficient: int = 0
    rejected_citation_count: int = 0
    official_source_count: int = 0
    prompt_injection_rejection_count: int = 0


class HelmBeaconWebSuggestionSummary(BaseModel):
    suggested: int = 0
    accepted: int = 0
    acceptance_rate_percent: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    accepted_matching_mode: int = 0
    accepted_after_confirmation: int = 0


class HelmBeaconProviderSummary(BaseModel):
    status: str
    provider_order: list[str] = Field(default_factory=list)
    configured_provider_count: int = 0
    usable_provider_count: int = 0
    required_provider_count: int = 0
    provider_redundancy_ok: bool = False
    provider_redundancy_status: str = "unavailable"
    missing_provider_count: int = 0


class HelmBeaconBrowserSummary(BaseModel):
    status: str
    runtime: str
    runtime_enabled: bool = False
    playwright_version: str | None = None
    expected_playwright_version: str | None = None
    playwright_version_ok: bool = False
    screenshot_store_ready: bool = False
    timeout_ms: int = 0
    max_runs_per_hour: int = 0


class HelmBeaconEvidenceSummary(BaseModel):
    status: str
    window_hours: int = 24
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    blocked: int = 0
    source_quality: HelmBeaconSourceQualitySummary = Field(
        default_factory=HelmBeaconSourceQualitySummary
    )
    web_suggestion: HelmBeaconWebSuggestionSummary = Field(
        default_factory=HelmBeaconWebSuggestionSummary
    )
    last_request: HelmBeaconLastRequest | None = None


class HelmBeaconRetentionSummary(BaseModel):
    mode: str
    evidence_retention_days: int
    screenshot_retention_days: int
    old_request_count: int
    screenshot_file_count: int
    screenshot_bytes: int


class HelmBeaconApprovalSummary(BaseModel):
    pending_browser_approvals: int = 0
    next_expires_at: str | None = None


class HelmBeaconQualityCanaryAlert(BaseModel):
    status: str = "missing"
    reason: str = "quality_canary_missing"
    severity: str = "warning"


class HelmBeaconQualityCanaryGroupSummary(BaseModel):
    case_count: int = 0
    passed: int = 0
    failed: int = 0
    failure_names: list[str] = Field(default_factory=list)
    case_names: list[str] = Field(default_factory=list)


class HelmBeaconQualityCanaryHistoryItem(BaseModel):
    status: str = "unknown"
    suite: str = "beacon_search_quality"
    suite_version: int = 0
    case_count: int = 0
    passed: int = 0
    failed: int = 0
    failure_names: list[str] = Field(default_factory=list)
    case_groups: dict[str, HelmBeaconQualityCanaryGroupSummary] = Field(
        default_factory=dict
    )
    request_id: str | None = None
    last_run_at: str | None = None
    age_hours: int = 0


class HelmBeaconQualityCanarySummary(HelmBeaconQualityCanaryHistoryItem):
    stale_after_hours: int = 0
    alert: HelmBeaconQualityCanaryAlert = Field(
        default_factory=HelmBeaconQualityCanaryAlert
    )
    history: list[HelmBeaconQualityCanaryHistoryItem] = Field(default_factory=list)


class HelmBeaconSummary(BaseModel):
    status: str
    checked_at: str
    provider: HelmBeaconProviderSummary
    browser: HelmBeaconBrowserSummary
    evidence: HelmBeaconEvidenceSummary
    retention: HelmBeaconRetentionSummary
    approvals: HelmBeaconApprovalSummary
    quality_canary: HelmBeaconQualityCanarySummary = Field(
        default_factory=HelmBeaconQualityCanarySummary
    )
    raw_web_content_is_untrusted: bool = True


class HelmControlSummary(BaseModel):
    mode: str = "read_only"
    alpha_authority: str = "required"
    mutations: str = "disabled"


class HelmSummaryOut(BaseModel):
    service: str = "jarvis-alpha"
    generated_at: str
    approvals: HelmApprovalSummary
    registry: HelmRegistrySummary
    posture: HelmPostureSummary
    beacon: HelmBeaconSummary
    controls: HelmControlSummary = Field(default_factory=HelmControlSummary)


class HelmActionProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str = Field(min_length=1, max_length=64)
    action_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=80)
    risk_tier: Literal["T1", "T2", "T3", "T4", "T5"]
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)


class HelmActionProposalOut(BaseModel):
    status: Literal["pending"]
    approval_queue_id: str
    connector_id: str
    action_id: str
    risk_tier: str


class HelmActionStatusItem(BaseModel):
    approval_queue_id: str
    connector_id: str
    action_id: str
    status: str
    risk_tier: str
    title: str
    requested_at: str | None = None
    expires_at: str | None = None


class HelmActionStatusOut(BaseModel):
    service: str = "jarvis-alpha"
    generated_at: str
    actions: list[HelmActionStatusItem]
    by_connector: dict[str, dict[str, int]] = Field(default_factory=dict)


def _row_value(row: object, key: str, default: object | None = None) -> object | None:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return cast(RowLike, row)[key]
    except (KeyError, TypeError):
        return default


def _str_value(row: object, key: str, default: str) -> str:
    value = _row_value(row, key, default)
    return str(value or default)


def _int_value(row: object, key: str) -> int:
    value = _row_value(row, key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str | bytes | bytearray):
        return int(value or 0)
    return 0


def _bool_value(row: object, key: str) -> bool:
    return bool(_row_value(row, key, False))


def _mapping_value(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _metadata_value(metadata: Mapping[str, object], key: str) -> object | None:
    return metadata.get(key)


def _metadata_str(
    metadata: Mapping[str, object],
    key: str,
    default: str | None = None,
) -> str | None:
    value = _metadata_value(metadata, key)
    if value is None:
        return default
    return str(value)


def _metadata_int(metadata: Mapping[str, object], key: str) -> int:
    value = _metadata_value(metadata, key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str | bytes | bytearray):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _metadata_bool(metadata: Mapping[str, object], key: str) -> bool:
    return bool(_metadata_value(metadata, key))


def _metadata_str_list(metadata: Mapping[str, object], key: str) -> list[str]:
    value = _metadata_value(metadata, key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _metadata_mapping_list(
    metadata: Mapping[str, object],
    key: str,
) -> list[Mapping[str, object]]:
    value = _metadata_value(metadata, key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _metadata_quality_canary_groups(
    metadata: Mapping[str, object],
    key: str,
) -> dict[str, HelmBeaconQualityCanaryGroupSummary]:
    value = _metadata_value(metadata, key)
    if not isinstance(value, Mapping):
        return {}

    groups: dict[str, HelmBeaconQualityCanaryGroupSummary] = {}
    for raw_name, raw_group in sorted(value.items()):
        group = _mapping_value(raw_group)
        if not group:
            continue
        name = str(raw_name)
        if not name:
            continue
        groups[name] = HelmBeaconQualityCanaryGroupSummary(
            case_count=_metadata_int(group, "case_count"),
            passed=_metadata_int(group, "passed"),
            failed=_metadata_int(group, "failed"),
            failure_names=_metadata_str_list(group, "failure_names"),
            case_names=_metadata_str_list(group, "case_names"),
        )
    return groups


def _risk_rank(tier: str) -> int:
    order = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}
    return order.get(tier, 0)


def _approval_summary(rows: list[object]) -> HelmApprovalSummary:
    by_tier: dict[str, int] = {}
    for row in rows:
        tier = _str_value(row, "risk_tier", "unclassified")
        count = _int_value(row, "count")
        by_tier[tier] = count

    highest = max(by_tier, key=_risk_rank) if by_tier else None
    return HelmApprovalSummary(
        pending_total=sum(by_tier.values()),
        by_tier=by_tier,
        highest_tier=highest,
    )


def _skill_summary(rows: list[object]) -> HelmSkillRegistrySummary:
    by_status: dict[str, int] = {}
    total = 0
    mutating = 0
    body_access = 0
    for row in rows:
        status = _str_value(row, "status", "unknown")
        count = _int_value(row, "count")
        by_status[status] = count
        total += count
        mutating += _int_value(row, "mutating")
        body_access += _int_value(row, "body_access")

    return HelmSkillRegistrySummary(
        total=total,
        by_status=by_status,
        mutating=mutating,
        body_access=body_access,
    )


def _agent_summary(rows: list[object]) -> HelmAgentRegistrySummary:
    by_status: dict[str, int] = {}
    by_risk_tier: dict[str, int] = {}
    total = 0
    enabled = 0
    for row in rows:
        count = _int_value(row, "count")
        status = _str_value(row, "status", "unknown")
        risk_tier = _str_value(row, "risk_tier", "unclassified")
        is_enabled = _bool_value(row, "enabled")

        total += count
        if is_enabled:
            enabled += count
        by_status[status] = by_status.get(status, 0) + count
        by_risk_tier[risk_tier] = by_risk_tier.get(risk_tier, 0) + count

    return HelmAgentRegistrySummary(
        total=total,
        enabled=enabled,
        by_status=by_status,
        by_risk_tier=by_risk_tier,
    )


def _gateway_posture(row: object | None) -> HelmGatewayPosture:
    if not row:
        return HelmGatewayPosture(state="missing", active=False)
    active = _bool_value(row, "is_active")
    return HelmGatewayPosture(
        state="registered" if active else "inactive", active=active
    )


def _security_agent_summary(rows: list[object]) -> HelmSecurityAgentSummary:
    by_status: dict[str, int] = {}
    enabled = 0
    for row in rows:
        status = _str_value(row, "status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        if _bool_value(row, "enabled"):
            enabled += 1

    return HelmSecurityAgentSummary(
        total=len(rows),
        enabled=enabled,
        by_status=by_status,
    )


def _beacon_last_request(
    metadata: Mapping[str, object],
) -> HelmBeaconLastRequest | None:
    last_request = _mapping_value(metadata.get("last_request"))
    if not last_request:
        return None
    return HelmBeaconLastRequest(
        id=_metadata_str(last_request, "id"),
        requester=_metadata_str(last_request, "requester"),
        selected_tool=_metadata_str(last_request, "selected_tool"),
        status=_metadata_str(last_request, "status"),
        created_at=_metadata_str(last_request, "created_at"),
        updated_at=_metadata_str(last_request, "updated_at"),
    )


def _beacon_source_quality(
    metadata: Mapping[str, object],
) -> HelmBeaconSourceQualitySummary:
    source_quality = _mapping_value(metadata.get("source_quality"))
    return HelmBeaconSourceQualitySummary(
        supported=_metadata_int(source_quality, "supported"),
        weak=_metadata_int(source_quality, "weak"),
        insufficient=_metadata_int(source_quality, "insufficient"),
        rejected_citation_count=_metadata_int(
            source_quality,
            "rejected_citation_count",
        ),
        official_source_count=_metadata_int(source_quality, "official_source_count"),
        prompt_injection_rejection_count=_metadata_int(
            source_quality,
            "prompt_injection_rejection_count",
        ),
    )


def _beacon_web_suggestion(
    metadata: Mapping[str, object],
) -> HelmBeaconWebSuggestionSummary:
    web_suggestion = _mapping_value(metadata.get("web_suggestion"))
    return HelmBeaconWebSuggestionSummary(
        suggested=_metadata_int(web_suggestion, "suggested"),
        accepted=_metadata_int(web_suggestion, "accepted"),
        acceptance_rate_percent=_metadata_int(
            web_suggestion,
            "acceptance_rate_percent",
        ),
        high_confidence=_metadata_int(web_suggestion, "high_confidence"),
        medium_confidence=_metadata_int(web_suggestion, "medium_confidence"),
        accepted_matching_mode=_metadata_int(
            web_suggestion,
            "accepted_matching_mode",
        ),
        accepted_after_confirmation=_metadata_int(
            web_suggestion,
            "accepted_after_confirmation",
        ),
    )


def _beacon_quality_canary(
    metadata: Mapping[str, object],
) -> HelmBeaconQualityCanarySummary:
    quality_canary = _mapping_value(metadata.get("quality_canary"))
    if not quality_canary:
        return HelmBeaconQualityCanarySummary()
    alert = _mapping_value(quality_canary.get("alert"))
    history = [
        _beacon_quality_canary_history_item(item)
        for item in _metadata_mapping_list(metadata, "quality_canary_history")
    ]
    return HelmBeaconQualityCanarySummary(
        status=_metadata_str(quality_canary, "status", "unknown") or "unknown",
        suite=_metadata_str(
            quality_canary,
            "suite",
            "beacon_search_quality",
        )
        or "beacon_search_quality",
        suite_version=_metadata_int(quality_canary, "suite_version"),
        case_count=_metadata_int(quality_canary, "case_count"),
        passed=_metadata_int(quality_canary, "passed"),
        failed=_metadata_int(quality_canary, "failed"),
        failure_names=_metadata_str_list(quality_canary, "failure_names"),
        case_groups=_metadata_quality_canary_groups(quality_canary, "case_groups"),
        request_id=_metadata_str(quality_canary, "request_id"),
        last_run_at=_metadata_str(quality_canary, "last_run_at"),
        age_hours=_metadata_int(quality_canary, "age_hours"),
        stale_after_hours=_metadata_int(quality_canary, "stale_after_hours"),
        alert=HelmBeaconQualityCanaryAlert(
            status=_metadata_str(alert, "status", "missing") or "missing",
            reason=_metadata_str(alert, "reason", "quality_canary_missing")
            or "quality_canary_missing",
            severity=_metadata_str(alert, "severity", "warning") or "warning",
        ),
        history=history,
    )


def _beacon_quality_canary_history_item(
    metadata: Mapping[str, object],
) -> HelmBeaconQualityCanaryHistoryItem:
    return HelmBeaconQualityCanaryHistoryItem(
        status=_metadata_str(metadata, "status", "unknown") or "unknown",
        suite=_metadata_str(metadata, "suite", "beacon_search_quality")
        or "beacon_search_quality",
        suite_version=_metadata_int(metadata, "suite_version"),
        case_count=_metadata_int(metadata, "case_count"),
        passed=_metadata_int(metadata, "passed"),
        failed=_metadata_int(metadata, "failed"),
        failure_names=_metadata_str_list(metadata, "failure_names"),
        case_groups=_metadata_quality_canary_groups(metadata, "case_groups"),
        request_id=_metadata_str(metadata, "request_id"),
        last_run_at=_metadata_str(metadata, "last_run_at"),
        age_hours=_metadata_int(metadata, "age_hours"),
    )


def _datetime_or_none(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def _beacon_pending_browser_approvals(conn) -> HelmBeaconApprovalSummary:
    row = await conn.fetchrow(
        """
        SELECT COUNT(*)::INTEGER AS pending_browser_approvals,
               MIN(expires_at) AS next_expires_at
        FROM public.alpha_approval_queue
        WHERE status = 'pending'
          AND (expires_at IS NULL OR expires_at > NOW())
          AND action_class && ARRAY['beacon_browser_use']::TEXT[]
        """
    )
    return HelmBeaconApprovalSummary(
        pending_browser_approvals=_int_value(row, "pending_browser_approvals"),
        next_expires_at=_datetime_or_none(_row_value(row, "next_expires_at")),
    )


def _unavailable_beacon_summary() -> HelmBeaconSummary:
    return HelmBeaconSummary(
        status="degraded",
        checked_at=datetime.now(UTC).isoformat(),
        provider=HelmBeaconProviderSummary(
            status="unavailable",
            provider_order=[],
            configured_provider_count=0,
            usable_provider_count=0,
            required_provider_count=0,
            provider_redundancy_ok=False,
            provider_redundancy_status="unavailable",
            missing_provider_count=0,
        ),
        browser=HelmBeaconBrowserSummary(
            status="unavailable",
            runtime="disabled",
        ),
        evidence=HelmBeaconEvidenceSummary(
            status="unavailable",
        ),
        retention=HelmBeaconRetentionSummary(
            mode="report_only",
            evidence_retention_days=0,
            screenshot_retention_days=0,
            old_request_count=0,
            screenshot_file_count=0,
            screenshot_bytes=0,
        ),
        approvals=HelmBeaconApprovalSummary(),
        quality_canary=HelmBeaconQualityCanarySummary(),
    )


async def _beacon_summary(conn) -> HelmBeaconSummary:
    try:
        health = await build_beacon_health(conn)
    except Exception as exc:
        logger.warning("helm beacon summary unavailable: %s", exc)
        return _unavailable_beacon_summary()

    gateway_check = health.checks.get("gateway")
    browser_check = health.checks.get("browser_runtime")
    evidence_check = health.checks.get("recent_evidence")

    gateway_metadata = (
        _mapping_value(gateway_check.metadata) if gateway_check is not None else {}
    )
    browser_metadata = (
        _mapping_value(browser_check.metadata) if browser_check is not None else {}
    )
    evidence_metadata = (
        _mapping_value(evidence_check.metadata) if evidence_check is not None else {}
    )
    approvals = await _beacon_pending_browser_approvals(conn)

    return HelmBeaconSummary(
        status=health.status,
        checked_at=health.checked_at.isoformat(),
        provider=HelmBeaconProviderSummary(
            status=gateway_check.status if gateway_check is not None else "unavailable",
            provider_order=_metadata_str_list(gateway_metadata, "provider_order"),
            configured_provider_count=_metadata_int(
                gateway_metadata,
                "configured_provider_count",
            ),
            usable_provider_count=_metadata_int(
                gateway_metadata,
                "usable_provider_count",
            ),
            required_provider_count=_metadata_int(
                gateway_metadata,
                "required_provider_count",
            ),
            provider_redundancy_ok=_metadata_bool(
                gateway_metadata,
                "provider_redundancy_ok",
            ),
            provider_redundancy_status=_metadata_str(
                gateway_metadata,
                "provider_redundancy_status",
                "unavailable",
            )
            or "unavailable",
            missing_provider_count=_metadata_int(
                gateway_metadata,
                "missing_provider_count",
            ),
        ),
        browser=HelmBeaconBrowserSummary(
            status=browser_check.status if browser_check is not None else "unavailable",
            runtime=_metadata_str(browser_metadata, "runtime", "disabled")
            or "disabled",
            runtime_enabled=_metadata_bool(browser_metadata, "runtime_enabled"),
            playwright_version=_metadata_str(
                browser_metadata,
                "installed_playwright_version",
            ),
            expected_playwright_version=_metadata_str(
                browser_metadata,
                "expected_playwright_version",
            ),
            playwright_version_ok=_metadata_bool(
                browser_metadata,
                "playwright_version_ok",
            ),
            screenshot_store_ready=(
                _metadata_bool(browser_metadata, "screenshot_dir_configured")
                and _metadata_bool(browser_metadata, "screenshot_dir_exists")
                and _metadata_bool(browser_metadata, "screenshot_dir_writable")
            ),
            timeout_ms=_metadata_int(browser_metadata, "timeout_ms"),
            max_runs_per_hour=_metadata_int(browser_metadata, "max_runs_per_hour"),
        ),
        evidence=HelmBeaconEvidenceSummary(
            status=evidence_check.status
            if evidence_check is not None
            else "unavailable",
            window_hours=_metadata_int(evidence_metadata, "window_hours") or 24,
            total=_metadata_int(evidence_metadata, "total"),
            succeeded=_metadata_int(evidence_metadata, "succeeded"),
            failed=_metadata_int(evidence_metadata, "failed"),
            blocked=_metadata_int(evidence_metadata, "blocked"),
            source_quality=_beacon_source_quality(evidence_metadata),
            web_suggestion=_beacon_web_suggestion(evidence_metadata),
            last_request=_beacon_last_request(evidence_metadata),
        ),
        retention=HelmBeaconRetentionSummary(
            mode=health.retention.mode,
            evidence_retention_days=health.retention.evidence_retention_days,
            screenshot_retention_days=health.retention.screenshot_retention_days,
            old_request_count=health.retention.old_request_count,
            screenshot_file_count=health.retention.screenshot_file_count,
            screenshot_bytes=health.retention.screenshot_bytes,
        ),
        approvals=approvals,
        quality_canary=_beacon_quality_canary(evidence_metadata),
    )


def _family_base_url() -> str:
    value = os.environ.get("JARVIS_FAMILY_API_URL", "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="family_api_not_configured")
    return value.rstrip("/")


def _family_id() -> str:
    value = os.environ.get("JARVIS_FAMILY_ID", "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="family_id_not_configured")
    return value


def _family_verify_tls() -> bool:
    return os.environ.get("JARVIS_FAMILY_VERIFY_TLS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _family_service_private_key() -> str:
    configured = (
        os.environ.get("ALPHA_FAMILY_SERVICE_PRIVATE_KEY_PATH", "").strip()
        or os.environ.get("JARVIS_ALPHA_SERVICE_PRIVATE_KEY_PATH", "").strip()
    )
    key_path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / "jarvis/pki/services/brain_private.pem"
    )
    return key_path.read_text(encoding="utf-8")


def _family_service_token() -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": os.environ.get("JARVIS_ALPHA_SERVICE_SUB", "brain"),
        "iss": os.environ.get("JARVIS_ALPHA_SERVICE_ISS", "brain"),
        "actor_type": "service",
        "family_id": _family_id(),
        "scopes": [_FAMILY_HELM_SCOPE],
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + 300,
    }
    return jwt.encode(payload, _family_service_private_key(), algorithm="RS256")


def _financial_base_url() -> str | None:
    value = os.environ.get("JARVIS_FINANCIAL_API_URL", "").strip()
    return value.rstrip("/") if value else None


def _financial_verify_tls() -> bool:
    return os.environ.get("JARVIS_FINANCIAL_VERIFY_TLS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _financial_summary_path() -> str:
    value = os.environ.get("JARVIS_FINANCIAL_HELM_SUMMARY_PATH", "").strip()
    return value or "/monitor/helm-summary"


def _secret_or_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        secret = get_secret(name)
    except Exception:
        return None
    return str(secret).strip() or None


def _financial_monitor_token() -> str | None:
    return _secret_or_env("JARVIS_FIN_SECURITY_POSTURE_TOKEN") or _secret_or_env(
        "FINANCIAL_SECURITY_POSTURE_TOKEN"
    )


def _iso_value(value: object | None) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _json_object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _status_counts(actions: list[HelmActionStatusItem]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for action in actions:
        connector_counts = counts.setdefault(action.connector_id, {})
        connector_counts[action.status] = connector_counts.get(action.status, 0) + 1
    return counts


def _extract_action_class(action_classes: object, prefix: str, fallback: str) -> str:
    if isinstance(action_classes, list):
        for action_class in action_classes:
            if isinstance(action_class, str) and action_class.startswith(prefix):
                return action_class.removeprefix(prefix)
    return fallback


def _title_from_description(description: str) -> str:
    marker = " - "
    if description.startswith("Helm proposal: ") and marker in description:
        return description.split(marker, 1)[1]
    return description


def _helm_action_item(row: object) -> HelmActionStatusItem:
    action_classes = _row_value(row, "action_class", [])
    connector_id = _extract_action_class(action_classes, "connector:", "unknown")
    action_id = _extract_action_class(action_classes, "action:", "unknown")
    description = _str_value(row, "description", "Helm proposal")
    return HelmActionStatusItem(
        approval_queue_id=str(_row_value(row, "id", "")),
        connector_id=connector_id,
        action_id=action_id,
        status=_str_value(row, "status", "unknown"),
        risk_tier=_str_value(row, "risk_tier", "T5"),
        title=_title_from_description(description),
        requested_at=_iso_value(_row_value(row, "requested_at")),
        expires_at=_iso_value(_row_value(row, "expires_at")),
    )


async def _helm_action_status_items(
    conn: Any,
    *,
    connector_id: str | None = None,
    limit: int = 50,
) -> list[HelmActionStatusItem]:
    action_filter = ["helm_action_proposal"]
    if connector_id:
        action_filter.append(f"connector:{connector_id}")
    rows = await conn.fetch(
        """
        SELECT id, action_class, risk_tier, status, description, requested_at, expires_at
        FROM public.alpha_approval_queue
        WHERE action_class @> $1::TEXT[]
          AND status IN ('pending', 'approved', 'denied', 'expired', 'executed')
        ORDER BY requested_at DESC
        LIMIT $2
        """,
        action_filter,
        limit,
    )
    return [_helm_action_item(row) for row in rows]


async def _optional_financial_payload() -> dict[str, Any]:
    base_url = _financial_base_url()
    if not base_url:
        return {}
    token = _financial_monitor_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(
            timeout=5.0,
            verify=_financial_verify_tls(),
        ) as client:
            response = await client.get(
                f"{base_url}{_financial_summary_path()}",
                headers=headers,
            )
    except (OSError, httpx.HTTPError):
        return {"status": "unavailable"}

    if response.status_code >= 400:
        return {"status": "unavailable"}
    try:
        payload = response.json()
    except ValueError:
        return {"status": "unavailable"}
    return _json_object(payload)


def _financial_readiness(payload: dict[str, Any]) -> str:
    paper = _json_object(payload.get("paper"))
    if isinstance(paper.get("readiness"), str):
        return str(paper["readiness"])
    if isinstance(payload.get("paper_readiness"), dict):
        value = _json_object(payload["paper_readiness"]).get("status")
        if isinstance(value, str):
            return value
    return "brokered"


def _financial_net_worth(payload: dict[str, Any]) -> str:
    net_worth = _json_object(payload.get("net_worth"))
    if isinstance(net_worth.get("status"), str):
        return str(net_worth["status"])
    return "brokered"


def _count_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for key, count in value.items():
        if isinstance(key, str) and isinstance(count, int):
            out[key] = count
    return out


def _safe_public_fields(
    payload: dict[str, Any],
    key: str,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    source = _json_object(payload.get(key))
    out: dict[str, Any] = {}
    for field in fields:
        if field not in source:
            continue
        value = source.get(field)
        if isinstance(value, str | int) or value is None:
            out[field] = value
        elif field == "counts":
            out[field] = _count_map(value)
    return out


def _financial_net_worth_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = _safe_public_fields(payload, "net_worth", ("sources", "included_sources"))
    out["status"] = _financial_net_worth(payload)
    return out


def _financial_plaid_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = _safe_public_fields(
        payload,
        "plaid",
        (
            "status",
            "coverage",
            "connected_sources",
            "planned_sources",
            "included_sources",
            "active_accounts",
            "included_accounts",
            "connected_items",
        ),
    )
    return out or {"status": "unknown", "coverage": "unknown"}


def _financial_kill_switch_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = _safe_public_fields(
        payload,
        "kill_switch",
        ("status", "state", "restriction_level", "deciding_source"),
    )
    return out or {"status": "unknown"}


def _financial_freshness_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = _safe_public_fields(payload, "freshness", ("status", "stale_flags", "counts"))
    return out or {"status": "unknown", "stale_flags": 0, "counts": {}}


async def _family_service_json(path: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=5.0,
            verify=_family_verify_tls(),
        ) as client:
            response = await client.get(
                f"{_family_base_url()}{path}",
                headers={"Authorization": f"Bearer {_family_service_token()}"},
            )
    except OSError as exc:
        raise HTTPException(
            status_code=503, detail="family_summary_unavailable"
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="family_summary_unavailable"
        ) from exc

    if response.status_code == 401 or response.status_code == 403:
        raise HTTPException(status_code=502, detail="family_service_scope_rejected")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="family_summary_unavailable")

    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="family_summary_invalid")
    return payload


def _proposal_parameters_hash(body: HelmActionProposalRequest) -> str:
    canonical = json.dumps(
        body.model_dump(exclude={"idempotency_key"}),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _proposal_nonce(body: HelmActionProposalRequest) -> str:
    if body.idempotency_key:
        return body.idempotency_key
    return f"helm:{body.connector_id}:{body.action_id}:{_proposal_parameters_hash(body)[:16]}"


def _validate_action_proposal(body: HelmActionProposalRequest) -> None:
    if body.connector_id not in _HELM_ACTION_CONNECTORS:
        raise HTTPException(status_code=400, detail="unsupported_connector")
    if body.risk_tier not in _HELM_RISK_TIERS:
        raise HTTPException(status_code=400, detail="unsupported_risk_tier")


@router.get("/summary", response_model=HelmSummaryOut)
async def helm_summary(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> HelmSummaryOut:
    """Return a redacted, read-only Alpha summary for Helm."""
    check_scopes(request, "helm.read", "admin")
    actor = str(getattr(request.state, "user_id", "unknown"))

    async with platform_admin_connection(
        source="http",
        audit_actor=f"helm_summary:{actor}",
    ) as conn:
        approval_rows = await conn.fetch(
            """
            SELECT COALESCE(risk_tier, 'unclassified') AS risk_tier,
                   COUNT(*)::INTEGER AS count
            FROM public.alpha_approval_queue
            WHERE status = 'pending'
              AND (expires_at IS NULL OR expires_at > NOW())
            GROUP BY COALESCE(risk_tier, 'unclassified')
            ORDER BY risk_tier ASC
            """
        )
        skill_rows = await conn.fetch(
            """
            SELECT COALESCE(status, 'unknown') AS status,
                   COUNT(*)::INTEGER AS count,
                   COUNT(*) FILTER (WHERE mutates_state)::INTEGER AS mutating,
                   COUNT(*) FILTER (WHERE body_access)::INTEGER AS body_access
            FROM public.alpha_skill_registry
            GROUP BY COALESCE(status, 'unknown')
            ORDER BY status ASC
            """
        )
        agent_rows = await conn.fetch(
            """
            SELECT COALESCE(status, 'unknown') AS status,
                   COALESCE(risk_tier, 'unclassified') AS risk_tier,
                   enabled,
                   COUNT(*)::INTEGER AS count
            FROM public.alpha_agents
            GROUP BY COALESCE(status, 'unknown'), COALESCE(risk_tier, 'unclassified'), enabled
            ORDER BY status ASC, risk_tier ASC, enabled DESC
            """
        )
        gateway_row = await conn.fetchrow(
            """
            SELECT is_active
            FROM public.alpha_node_registry
            WHERE name = 'gateway'
            LIMIT 1
            """
        )
        security_agent_rows = await conn.fetch(
            """
            SELECT status, enabled
            FROM public.alpha_agents
            WHERE agent_id = ANY($1::TEXT[])
            ORDER BY agent_id ASC
            """,
            list(_SECURITY_AGENT_IDS),
        )
        beacon_summary = await _beacon_summary(conn)

    return HelmSummaryOut(
        generated_at=datetime.now(UTC).isoformat(),
        approvals=_approval_summary(list(approval_rows)),
        registry=HelmRegistrySummary(
            skills=_skill_summary(list(skill_rows)),
            agents=_agent_summary(list(agent_rows)),
        ),
        posture=HelmPostureSummary(
            gateway=_gateway_posture(gateway_row),
            security_agents=_security_agent_summary(list(security_agent_rows)),
        ),
        beacon=beacon_summary,
    )


@router.get("/family/summary")
async def helm_family_summary(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    """Return a Family home summary through Alpha-held service identity."""
    check_scopes(request, "helm.read", "admin")
    actor = str(getattr(request.state, "user_id", "unknown"))

    payload = await _family_service_json("/v1/helm/home-summary")

    return {
        **payload,
        "_broker": {
            "authority": "jarvis-alpha",
            "source": "jarvis-family",
            "actor": actor,
            "mode": "service_scope",
        },
    }


@router.get("/financial/summary")
async def helm_financial_summary(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    """Return a redacted Financial posture summary through Alpha authority."""
    check_scopes(request, "helm.read", "admin")
    actor = str(getattr(request.state, "user_id", "unknown"))

    async with platform_admin_connection(
        source="http",
        audit_actor=f"helm_financial_summary:{actor}",
    ) as conn:
        actions = await _helm_action_status_items(conn, connector_id="financial")

    downstream = await _optional_financial_payload()
    pending = sum(1 for action in actions if action.status == "pending")
    generated_at = datetime.now(UTC).isoformat()
    return {
        "service": "jarvis-financial",
        "generated_at": generated_at,
        "status": "brokered",
        "paper": {
            "status": "read_only",
            "readiness": _financial_readiness(downstream),
        },
        "net_worth": _financial_net_worth_payload(downstream),
        "plaid": _financial_plaid_payload(downstream),
        "kill_switch": _financial_kill_switch_payload(downstream),
        "freshness": _financial_freshness_payload(downstream),
        "pending_approvals": pending,
        "approvals": {
            "pending": pending,
            "items": [action.model_dump() for action in actions[:10]],
        },
        "_broker": {
            "authority": "jarvis-alpha",
            "source": "jarvis-financial",
            "actor": actor,
            "mode": "alpha_queue_status",
        },
    }


@router.get("/medical/summary")
async def helm_medical_summary(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    """Return a redacted Medical safety summary through Alpha authority."""
    check_scopes(request, "helm.read", "admin")
    actor = str(getattr(request.state, "user_id", "unknown"))

    async with platform_admin_connection(
        source="http",
        audit_actor=f"helm_medical_summary:{actor}",
    ) as conn:
        actions = await _helm_action_status_items(conn, connector_id="medical")

    payload = await _family_service_json("/v1/helm/medical-summary")
    pending = sum(1 for action in actions if action.status == "pending")
    return {
        **payload,
        "pending_approvals": pending,
        "approvals": {
            "pending": pending,
            "items": [action.model_dump() for action in actions[:10]],
        },
        "_broker": {
            "authority": "jarvis-alpha",
            "source": "jarvis-family",
            "actor": actor,
            "mode": "service_scope",
        },
    }


@router.get("/actions/status", response_model=HelmActionStatusOut)
async def helm_action_status(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> HelmActionStatusOut:
    """Return redacted status for Helm-originated Alpha approval rows."""
    check_scopes(request, "helm.read", "admin")
    actor = str(getattr(request.state, "user_id", "unknown"))

    async with platform_admin_connection(
        source="http",
        audit_actor=f"helm_action_status:{actor}",
    ) as conn:
        actions = await _helm_action_status_items(conn)

    return HelmActionStatusOut(
        generated_at=datetime.now(UTC).isoformat(),
        actions=actions,
        by_connector=_status_counts(actions),
    )


@router.post("/actions/propose", response_model=HelmActionProposalOut)
async def helm_action_proposal(
    request: Request,
    body: HelmActionProposalRequest,
    _user_id: str = Depends(require_auth),
) -> HelmActionProposalOut:
    """Queue a Helm-proposed action into Alpha's approval queue."""
    check_scopes(request, "helm.read", "admin")
    _validate_action_proposal(body)

    actor_sub = str(getattr(request.state, "user_id", "unknown"))
    actor_type = str(getattr(request.state, "actor_type", "user"))
    parameters_hash = _proposal_parameters_hash(body)
    nonce = _proposal_nonce(body)
    description = f"Helm proposal: {body.domain} - {body.title}"

    async with platform_admin_connection(
        source="http",
        audit_actor=f"helm_action:{actor_sub}",
    ) as conn:
        existing = await conn.fetchrow(
            """
            SELECT id, risk_tier
            FROM public.alpha_approval_queue
            WHERE nonce = $1
               OR (actor_sub = $2 AND parameters_hash = $3 AND status = 'pending')
            ORDER BY requested_at DESC
            LIMIT 1
            """,
            nonce,
            actor_sub,
            parameters_hash,
        )
        if existing is not None:
            return HelmActionProposalOut(
                status="pending",
                approval_queue_id=str(existing["id"]),
                connector_id=body.connector_id,
                action_id=body.action_id,
                risk_tier=str(existing["risk_tier"]),
            )

        queue_id = await conn.fetchval(
            """
            SELECT public.enqueue_approval_request(
                $1::text[], $2::text, $3::text, $4::text, $5::text, $6::text, $7::text
            )
            """,
            [
                "helm_action_proposal",
                f"connector:{body.connector_id}",
                f"action:{body.action_id}",
            ],
            body.risk_tier,
            actor_sub,
            actor_type,
            description,
            parameters_hash,
            nonce,
        )

    if queue_id is None:
        raise HTTPException(status_code=500, detail="approval_queue_write_failed")

    return HelmActionProposalOut(
        status="pending",
        approval_queue_id=str(queue_id),
        connector_id=body.connector_id,
        action_id=body.action_id,
        risk_tier=body.risk_tier,
    )
