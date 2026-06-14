from __future__ import annotations

import json
from typing import Literal
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.db.rls import rls_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.memory_consolidation import collect_memory_consolidation_report
from brain.services.memory_consolidation_proposals import (
    PersistedMemoryConsolidationProposal,
    build_memory_consolidation_proposal_records,
    create_reviewed_memory_consolidation_proposals,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")
router = APIRouter(prefix="/v1/memory/consolidation", tags=["memory-consolidation"])


class CreateMemoryConsolidationProposalsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str | None = Field(default=None, min_length=1, max_length=128)
    semantic_limit: int = Field(default=200, ge=1, le=500)
    conversation_limit: int = Field(default=200, ge=1, le=500)
    dry_run: bool = False


class MemoryConsolidationProposalItem(BaseModel):
    proposal_id: str | None
    candidate_id: str
    candidate_action: str
    proposed_action: str
    executable: bool
    status: str
    approval_queue_id: str | None
    parameters_hash: str


class CreateMemoryConsolidationProposalsResponse(BaseModel):
    status: Literal["dry_run", "queued"]
    target_user_id: str
    report_status: str
    candidate_count: int
    executable_count: int
    informational_count: int
    write_actions_enabled: bool
    proposals: list[MemoryConsolidationProposalItem]


class MemoryConsolidationExecutionResponse(BaseModel):
    status: str
    proposal_id: str
    result: dict


@router.post("/proposals", response_model=CreateMemoryConsolidationProposalsResponse)
async def create_memory_consolidation_proposals(
    body: CreateMemoryConsolidationProposalsRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> CreateMemoryConsolidationProposalsResponse:
    """Create reviewed consolidation proposals from the read-only Dream report."""

    check_scopes(request, "memory.write", "admin")
    target_user_id = _target_user_id(request, body.target_user_id)
    actor_sub = (
        str(getattr(request.state, "user_sub", None) or "")
        or str(getattr(request.state, "user_id", None) or "")
        or "unknown"
    )
    actor_type = str(getattr(request.state, "actor_type", "user") or "user")

    async with rls_connection(request) as conn:
        report = await collect_memory_consolidation_report(
            conn,
            target_user_id,
            semantic_limit=body.semantic_limit,
            conversation_limit=body.conversation_limit,
        )
        records = build_memory_consolidation_proposal_records(report)
        if body.dry_run:
            proposals = [
                MemoryConsolidationProposalItem(
                    proposal_id=None,
                    candidate_id=record.candidate_id,
                    candidate_action=record.candidate_action,
                    proposed_action=record.proposed_action,
                    executable=record.executable,
                    status=record.initial_status,
                    approval_queue_id=None,
                    parameters_hash=record.parameters_hash,
                )
                for record in records
            ]
            status: Literal["dry_run", "queued"] = "dry_run"
        else:
            persisted = await create_reviewed_memory_consolidation_proposals(
                conn,
                report=report,
                actor_sub=actor_sub,
                actor_type=actor_type,
            )
            proposals = [_proposal_item(item) for item in persisted]
            status = "queued"

    executable_count = sum(1 for proposal in proposals if proposal.executable)
    informational_count = len(proposals) - executable_count
    logger.info(
        "MEMORY_CONSOLIDATION_PROPOSALS_CREATED",
        extra={
            "event": "MEMORY_CONSOLIDATION_PROPOSALS_CREATED",
            "target_user_id": str(target_user_id),
            "candidate_count": len(proposals),
            "executable_count": executable_count,
            "dry_run": body.dry_run,
        },
    )
    return CreateMemoryConsolidationProposalsResponse(
        status=status,
        target_user_id=str(target_user_id),
        report_status=str(report.get("status") or "unknown"),
        candidate_count=int(report.get("candidate_count") or 0),
        executable_count=executable_count,
        informational_count=informational_count,
        write_actions_enabled=False,
        proposals=proposals,
    )


@router.post(
    "/proposals/{proposal_id}/execute",
    response_model=MemoryConsolidationExecutionResponse,
)
async def execute_memory_consolidation_proposal(
    proposal_id: UUID,
    request: Request,
    x_approval_token: str = Header(alias="X-Approval-Token"),
    _user_id: str = Depends(require_auth),
) -> MemoryConsolidationExecutionResponse:
    """Execute an approved archive or semantic-promotion proposal.

    ADR-0026 requires the executor to validate proposal-bound approval
    provenance. The header must contain the proposal-specific Approval Gateway
    queue id, not merely a flipped proposal status.
    """

    check_scopes(request, "memory.write", "admin")
    approval_queue_id = _uuid_header(x_approval_token, "X-Approval-Token")
    actor_sub = (
        str(getattr(request.state, "user_sub", None) or "")
        or str(getattr(request.state, "user_id", None) or "")
        or "unknown"
    )
    async with rls_connection(request) as conn:
        result = await conn.fetchval(
            """
            SELECT public.execute_memory_consolidation_proposal(
                $1::uuid,
                $2::uuid,
                $3
            )
            """,
            str(proposal_id),
            str(approval_queue_id),
            actor_sub,
        )
    payload = _json_result(result)
    return MemoryConsolidationExecutionResponse(
        status=str(payload.get("status") or "unknown"),
        proposal_id=str(proposal_id),
        result=payload,
    )


@router.post(
    "/proposals/{proposal_id}/revert",
    response_model=MemoryConsolidationExecutionResponse,
)
async def revert_memory_consolidation_proposal(
    proposal_id: UUID,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> MemoryConsolidationExecutionResponse:
    """Revert an executed archive proposal through the ledger undo path."""

    check_scopes(request, "memory.write", "admin")
    async with rls_connection(request) as conn:
        result = await conn.fetchval(
            "SELECT public.revert_consolidation($1::uuid)",
            str(proposal_id),
        )
    payload = _json_result(result)
    return MemoryConsolidationExecutionResponse(
        status=str(payload.get("status") or "unknown"),
        proposal_id=str(proposal_id),
        result=payload,
    )


def _proposal_item(
    item: PersistedMemoryConsolidationProposal,
) -> MemoryConsolidationProposalItem:
    return MemoryConsolidationProposalItem(
        proposal_id=item.proposal_id,
        candidate_id=item.candidate_id,
        candidate_action=item.candidate_action,
        proposed_action=item.proposed_action,
        executable=item.executable,
        status=item.status,
        approval_queue_id=item.approval_queue_id,
        parameters_hash=item.parameters_hash,
    )


def _target_user_id(request: Request, requested: str | None) -> UUID:
    raw_value = requested or getattr(request.state, "user_id", None)
    if not raw_value:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return UUID(str(raw_value))
    except ValueError:
        return uuid5(NAMESPACE_DNS, str(raw_value))


def _uuid_header(value: str, header_name: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{header_name} must be an approval queue UUID",
        ) from exc


def _json_result(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {"value": loaded}
    return {"value": value}
