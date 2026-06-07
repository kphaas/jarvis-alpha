"""Spark runtime readiness checks.

Readiness output is metadata-only: it reports missing files, missing config
keys, and connector health without returning secret values or message content.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from brain.services.bluebubbles_client import (
    BlueBubblesReadOnlyClient,
    load_spark_bluebubbles_policy,
)
from brain.services.spark_imessage_drafts import (
    APPROVED_CHAT_GUID_ENV,
    _approval_specific_env_name,
    _optional_secret,
)
from brain.services.spark_persona_guardrails import load_spark_guardrails
from brain.services.spark_voice_ingest import load_approved_voice_sources


class SparkRuntimeCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    detail: str


class SparkRuntimeReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    ready: bool
    checks: list[SparkRuntimeCheck]


async def check_spark_runtime_readiness(
    *,
    principal_id: str = "ken",
    vault_root: str | Path | None = None,
    bluebubbles_client: BlueBubblesReadOnlyClient | None = None,
) -> SparkRuntimeReadiness:
    checks: list[SparkRuntimeCheck] = []
    root = _vault_root(vault_root)

    _check_path(
        checks,
        "personality_vault",
        root,
        "Spark personality vault is readable",
    )
    _check_path(
        checks,
        "ken_sources",
        root / "spark" / "principals" / principal_id / "sources.yml",
        "Principal source approvals are readable",
    )
    _check_path(
        checks,
        "ken_voice",
        root / "spark" / "principals" / principal_id / "voice.md",
        "Principal voice guidance is readable",
    )
    _check_guardrails(checks)
    _check_bluebubbles_policy(checks, root)
    _check_approved_imessage_source(checks, root, principal_id)
    _check_llm_gateway_token(checks)
    await _check_bluebubbles_health(checks, bluebubbles_client)

    return SparkRuntimeReadiness(
        principal_id=principal_id,
        ready=all(check.status == "passed" for check in checks),
        checks=checks,
    )


def _vault_root(vault_root: str | Path | None) -> Path:
    raw = (
        str(vault_root)
        if vault_root is not None
        else os.environ.get("SPARK_PERSONALITY_VAULT")
        or os.environ.get("JARVIS_PERSONALITY_VAULT")
        or "~/jarvis-personality"
    )
    return Path(raw).expanduser()


def _check_path(
    checks: list[SparkRuntimeCheck],
    name: str,
    path: Path,
    passed_detail: str,
) -> None:
    checks.append(
        SparkRuntimeCheck(
            name=name,
            status="passed" if path.exists() else "failed",
            detail=passed_detail if path.exists() else f"Missing path: {path}",
        )
    )


def _check_guardrails(checks: list[SparkRuntimeCheck]) -> None:
    try:
        state = load_spark_guardrails()
    except Exception:
        checks.append(
            SparkRuntimeCheck(
                name="guardrails",
                status="failed",
                detail="Spark guardrail state failed validation",
            )
        )
        return
    checks.append(
        SparkRuntimeCheck(
            name="guardrails",
            status="passed",
            detail=f"Guardrails loaded in {state.active_mode}",
        )
    )


def _check_bluebubbles_policy(checks: list[SparkRuntimeCheck], root: Path) -> None:
    try:
        policy = load_spark_bluebubbles_policy(root)
    except Exception:
        checks.append(
            SparkRuntimeCheck(
                name="bluebubbles_policy",
                status="failed",
                detail="BlueBubbles read-only policy failed validation",
            )
        )
        return
    checks.append(
        SparkRuntimeCheck(
            name="bluebubbles_policy",
            status="passed",
            detail=f"{policy.connector_mode}/{policy.drafting_mode}",
        )
    )


def _check_approved_imessage_source(
    checks: list[SparkRuntimeCheck],
    root: Path,
    principal_id: str,
) -> None:
    try:
        records = load_approved_voice_sources(root, principal_id)
    except Exception:
        checks.append(
            SparkRuntimeCheck(
                name="approved_imessage_source",
                status="failed",
                detail="Approved source records could not be loaded",
            )
        )
        return

    imessage_records = [record for record in records if record.source == "imessage"]
    if not imessage_records:
        checks.append(
            SparkRuntimeCheck(
                name="approved_imessage_source",
                status="failed",
                detail="No approved iMessage source record found",
            )
        )
        return

    checks.append(
        SparkRuntimeCheck(
            name="approved_imessage_source",
            status="passed",
            detail=f"{len(imessage_records)} approved iMessage source record(s)",
        )
    )

    configured = [
        record
        for record in imessage_records
        if _optional_secret(_approval_specific_env_name(record.approval_id))
        or _optional_secret(APPROVED_CHAT_GUID_ENV)
    ]
    checks.append(
        SparkRuntimeCheck(
            name="approved_chat_guid",
            status="passed" if configured else "failed",
            detail=(
                "Approved chat GUID secret is configured"
                if configured
                else "Approved chat GUID secret is missing"
            ),
        )
    )


def _check_llm_gateway_token(checks: list[SparkRuntimeCheck]) -> None:
    token_present = any(
        os.environ.get(name, "").strip()
        for name in ("GATEWAY_TOKEN", "ALPHA_BRAIN_SERVICE_TOKEN", "ALPHA_SERVICE_TOKEN")
    )
    checks.append(
        SparkRuntimeCheck(
            name="llm_gateway_token",
            status="passed" if token_present else "failed",
            detail=(
                "Gateway token is available for Spark LLM drafts"
                if token_present
                else "Gateway token missing for Spark LLM drafts"
            ),
        )
    )


async def _check_bluebubbles_health(
    checks: list[SparkRuntimeCheck],
    bluebubbles_client: BlueBubblesReadOnlyClient | None,
) -> None:
    try:
        client = bluebubbles_client or BlueBubblesReadOnlyClient()
        health = await client.health()
    except Exception:
        checks.append(
            SparkRuntimeCheck(
                name="bluebubbles_health",
                status="failed",
                detail="BlueBubbles server health check failed",
            )
        )
        return
    checks.append(
        SparkRuntimeCheck(
            name="bluebubbles_health",
            status="passed" if health.detected_imessage else "failed",
            detail=(
                "BlueBubbles detected iMessage account"
                if health.detected_imessage
                else "BlueBubbles did not report an active iMessage account"
            ),
        )
    )
