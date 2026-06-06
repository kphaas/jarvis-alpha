"""Spark persona guardrail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.spark_persona_guardrails import (
    SparkGuardrailState,
    load_spark_guardrails,
    save_spark_guardrails,
)
from jarvis_common.logging_config import get_logger

router = APIRouter(prefix="/v1/spark/persona", tags=["spark-persona"])
logger = get_logger("alpha_brain")


@router.get("/guardrails", response_model=SparkGuardrailState)
async def get_spark_guardrails(
    request: Request,
    _: str = Depends(require_auth),
) -> SparkGuardrailState:
    check_scopes(request, "spark.draft")
    try:
        return load_spark_guardrails()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_guardrails_load_failed"
        ) from exc


@router.put("/guardrails", response_model=SparkGuardrailState)
async def put_spark_guardrails(
    request: Request,
    payload: SparkGuardrailState,
    _: str = Depends(require_auth),
) -> SparkGuardrailState:
    check_scopes(request, "admin")
    try:
        saved = save_spark_guardrails(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="spark_guardrails_invalid") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="spark_guardrails_save_failed"
        ) from exc

    logger.info(
        "spark_guardrails_updated",
        extra={
            "event": "spark_guardrails_updated",
            "component": "spark_persona",
            "principal_id": saved.principal_id,
            "active_mode": saved.active_mode,
            "auto_send_enabled": saved.auto_send_enabled,
            "protected_topic_count": len(saved.protected_topics),
            "protected_relationship_count": len(saved.protected_relationships),
            "actor_sub": str(getattr(request.state, "user_id", "unknown")),
            "actor_type": str(getattr(request.state, "actor_type", "unknown")),
        },
    )
    return saved
