from __future__ import annotations

from typing import Literal
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
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
