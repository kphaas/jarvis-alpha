"""Privacy-scrub intake routes.

These routes only create local encrypted intake records. They do not scrape,
send opt-out actions, call public internet targets, or start runners.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.agents.privacy_scrub.config import (
    PrivacyScrubConfigError,
    load_privacy_crypto,
)
from brain.agents.privacy_scrub.crypto import PrivacyCrypto
from brain.agents.privacy_scrub.drafts import (
    CaseDraftInboxItem,
    CaseDraftDisposition,
    CreatedCaseDraft,
    PrivacyCaseDraftRepository,
    PrivacyDraftCaseNotFound,
    PrivacyDraftDispositionError,
    PrivacyDraftError,
    PrivacyDraftSubjectNotFound,
    PrivacyDraftTargetNotFound,
    RetrievedCaseDraft,
    TargetReviewPacket,
    list_approved_privacy_actions,
)
from brain.agents.privacy_scrub.identity import TupleType
from brain.agents.privacy_scrub.removal_control import (
    PrivacyRemovalControlRepository,
    RemovalBenchmark,
    RemovalControlSummary,
    RemovalLane,
    RemovalLens,
)
from brain.agents.privacy_scrub.removal_seed import (
    PrivacyRemovalControlSeedRepository,
    PrivacyRemovalSeedError,
    PrivacyRemovalSeedSubjectNotFound,
    PrivacyRemovalSeedTargetMissing,
    RemovalControlSeedResult,
)
from brain.agents.privacy_scrub.repository import (
    IdentityTupleInput,
    PrivacySubjectRepository,
    SubjectIntake,
)
from brain.agents.privacy_scrub.state import (
    StoredApprovedPrivacyAction,
    get_subject,
    insert_identity_tuple,
    list_targets,
    refresh_targets_cache,
    StoredPrivacyActionEvent,
)
from brain.agents.privacy_scrub.subjects import Role
from brain.agents.privacy_scrub.targets import load_all_targets
from brain.agents.privacy_scrub.workflow import (
    PrivacyActionWorkflowError,
    PrivacyActionWorkflowNotFound,
    PrivacyActionWorkflowRepository,
    PrivacyActionWorkflowResult,
    PrivacyCaseReport,
    PrivacyCaseTimeline,
    PrivacyCaseWorkflowReader,
)
from brain.db.rls import rls_connection
from brain.middleware.jwt_auth import require_auth

router = APIRouter(prefix="/v1/privacy", tags=["privacy"])


class IdentityTupleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tuple_type: TupleType
    value: str = Field(min_length=1)
    label: str | None = Field(default=None, min_length=1)


class SubjectCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_label: str = Field(min_length=1)
    role: Role
    jurisdiction: str = Field(default="US_GA", min_length=2)
    guardian_user_id: str | None = Field(default=None, min_length=1)
    payload: dict[str, object] = Field(default_factory=dict)
    identity_tuples: list[IdentityTupleIn] = Field(min_length=1)


class IdentityTupleCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tuple_type: TupleType
    value: str = Field(min_length=1)
    label: str | None = Field(default=None, min_length=1)


class SubjectCreateOut(BaseModel):
    subject_id: UUID
    status: str
    identity_tuple_count: int
    payload_key_version: str


class IdentityTupleCreateOut(BaseModel):
    subject_id: UUID
    identity_tuple_id: UUID | None
    tuple_type: TupleType
    key_version: str
    inserted: bool


class PrivacyTargetOut(BaseModel):
    id: str
    name: str
    category: str
    jurisdiction: str
    opt_out_method: str
    opt_out_url: str | None = None
    contact_email: str | None = None
    supports_minors: bool
    requires_sensitive_payload: bool
    requires_identity_document: bool
    avg_response_days: int | None = None
    last_verified: date | None = None
    notes: str | None = None
    yaml_source: str
    loaded_at: datetime | None = None


class PrivacyTargetsOut(BaseModel):
    count: int
    targets: list[PrivacyTargetOut]


class PrivacyTargetsRefreshOut(BaseModel):
    count: int
    source_label: str


class CaseDraftCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_ids: list[str] = Field(min_length=1, max_length=25)


class TargetReviewPacketOut(BaseModel):
    target_id: str
    target_name: str
    category: str
    jurisdiction: str
    opt_out_method: str
    approval_tier: str
    approval_reason: str
    legal_basis: str
    required_identifiers: list[str]
    available_identity_tuple_types: list[str]
    evidence_checklist: list[str]
    risk_flags: list[str]


class DraftActionOut(BaseModel):
    action_id: UUID
    target_id: str
    approval_tier: str
    status: str


class CaseDraftCreateOut(BaseModel):
    case_id: UUID
    subject_id: UUID
    status: str
    target_count: int
    action_count: int
    payload_key_version: str
    review_packets: list[TargetReviewPacketOut]
    actions: list[DraftActionOut]


class CaseDraftSummaryOut(BaseModel):
    case_id: UUID
    subject_id: UUID
    status: str
    target_count: int
    action_count: int
    highest_approval_tier: str | None
    payload_key_version: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseDraftListOut(BaseModel):
    count: int
    drafts: list[CaseDraftSummaryOut]


class CaseDraftDetailOut(CaseDraftSummaryOut):
    review_packets: list[TargetReviewPacketOut]
    actions: list[DraftActionOut]


class CaseDraftDispositionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator_note: str | None = Field(default=None, max_length=500)


class CaseDraftDispositionOut(BaseModel):
    case_id: UUID
    status: str
    disposition: str
    action_count: int
    highest_approval_tier: str | None
    queue_id: UUID | None = None


class ApprovedPrivacyActionOut(BaseModel):
    action_id: UUID
    case_id: UUID
    subject_id: UUID
    target_id: str
    target_name: str
    category: str
    jurisdiction: str
    opt_out_method: str
    approval_tier: str
    status: str
    approval_queue_id: UUID | None
    case_status: str
    manual_disposition: str | None = None
    manual_disposition_at: datetime | None = None
    manual_disposition_by: str | None = None
    manual_note_hash: str | None = None
    evidence_payload_hash: str | None = None
    workflow_payload_key_version: str | None = None
    sent_at: datetime | None = None
    confirmed_at: datetime | None = None
    verification_due_at: datetime | None = None
    error_code: str | None = None
    error_digest: str | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    avg_response_days: int | None = None


class ApprovedPrivacyActionsOut(BaseModel):
    count: int
    actions: list[ApprovedPrivacyActionOut]


class PrivacyActionManualDispositionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disposition: Literal["handled", "deferred", "blocked"]
    operator_note: str | None = Field(default=None, max_length=1000)
    evidence_reference: str | None = Field(default=None, max_length=1000)
    verification_due_at: datetime | None = None


class PrivacyActionVerificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["confirmed", "needs_followup", "failed"]
    operator_note: str | None = Field(default=None, max_length=1000)
    evidence_reference: str | None = Field(default=None, max_length=1000)
    verification_due_at: datetime | None = None


class PrivacyActionWorkflowOut(BaseModel):
    event_type: str
    action: ApprovedPrivacyActionOut


class PrivacyCaseEventOut(BaseModel):
    event_id: UUID
    action_id: UUID
    case_id: UUID
    target_id: str
    target_name: str
    event_type: str
    actor: str
    event_payload_hash: str | None = None
    created_at: datetime | None = None


class PrivacyCaseTimelineOut(BaseModel):
    case_id: UUID
    subject_id: UUID
    status: str
    event_count: int
    events: list[PrivacyCaseEventOut]


class PrivacyEvidenceManifestOut(BaseModel):
    status: Literal["complete", "attention"]
    action_count: int
    terminal_action_count: int
    open_action_count: int
    manual_note_hash_count: int
    evidence_payload_hash_count: int
    event_payload_hash_count: int
    missing_evidence_count: int


class PrivacyCaseReportOut(BaseModel):
    case_id: UUID
    subject_id: UUID
    status: str
    target_count: int
    action_count: int
    event_count: int
    generated_at: datetime
    actions: list[ApprovedPrivacyActionOut]
    events: list[PrivacyCaseEventOut]
    evidence_manifest: PrivacyEvidenceManifestOut


class PrivacyRemovalCountsOut(BaseModel):
    targets_total: int
    broker_targets: int
    public_record_targets: int
    authorizations_active: int
    adapter_profiles: int
    adapter_profiles_recurring: int
    evidence_items: int
    monitor_runs: int
    monitor_runs_due: int
    search_deindex_items: int
    public_record_triage_items: int
    approved_actions_open: int
    approved_actions_terminal: int


class PrivacyRemovalLaneOut(BaseModel):
    code: str
    label: str
    status: str
    north_star: str
    current_state: str
    next_step: str
    evidence_key: str
    metric: int


class PrivacyRemovalLensOut(BaseModel):
    code: str
    label: str
    status: str
    summary: str
    checkpoints: list[str]


class PrivacyRemovalBenchmarkOut(BaseModel):
    provider: str
    capability: str
    alpha_gap: str
    control: str


class PrivacyRemovalControlSummaryOut(BaseModel):
    generated_at: datetime
    mode: str
    outbound_enabled: bool
    counts: PrivacyRemovalCountsOut
    lanes: list[PrivacyRemovalLaneOut]
    lenses: list[PrivacyRemovalLensOut]
    benchmarks: list[PrivacyRemovalBenchmarkOut]


class PrivacyRemovalSeedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_authorization: Literal[True] = True


class PrivacyRemovalSeedCountsOut(BaseModel):
    authorizations_created: int
    authorizations_skipped: int
    evidence_created: int
    evidence_skipped: int
    monitor_runs_created: int
    monitor_runs_skipped: int
    search_deindex_created: int
    search_deindex_skipped: int
    public_record_triage_created: int
    public_record_triage_skipped: int
    total_created: int
    total_skipped: int


class PrivacyRemovalSeedOut(BaseModel):
    subject_id: UUID
    broker_target_id: str
    public_record_target_id: str | None
    payload_key_version: str
    generated_at: datetime
    counts: PrivacyRemovalSeedCountsOut


@router.post("/subjects", response_model=SubjectCreateOut)
async def create_privacy_subject(
    request: Request,
    body: SubjectCreateIn,
    user_id: str = Depends(require_auth),
) -> SubjectCreateOut:
    _assert_adult_or_admin_actor(request)
    crypto = _load_crypto_or_503()
    guardian_user_id = _guardian_user_id(user_id, body)

    try:
        intake = SubjectIntake(
            user_id=user_id,
            display_label=body.display_label,
            role=body.role,
            jurisdiction=body.jurisdiction,
            guardian_user_id=guardian_user_id,
            payload=body.payload,
            identity_tuples=tuple(
                _identity_tuple_input(item) for item in body.identity_tuples
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="privacy_subject_intake_invalid",
        ) from exc

    try:
        async with rls_connection(request) as conn:
            result = await PrivacySubjectRepository(conn, crypto).create_subject(intake)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="privacy_subject_intake_invalid",
        ) from exc

    return SubjectCreateOut(
        subject_id=result.subject.id,
        status=result.subject.status.value,
        identity_tuple_count=len(result.identity_tuple_ids),
        payload_key_version=result.subject.subject_payload_key_version,
    )


@router.post(
    "/subjects/{subject_id}/identity-tuples",
    response_model=IdentityTupleCreateOut,
)
async def add_privacy_identity_tuple(
    request: Request,
    subject_id: UUID,
    body: IdentityTupleCreateIn,
    _: str = Depends(require_auth),
) -> IdentityTupleCreateOut:
    _assert_adult_or_admin_actor(request)
    crypto = _load_crypto_or_503()

    try:
        async with rls_connection(request) as conn:
            subject = await get_subject(conn, subject_id)
            if subject is None:
                raise HTTPException(status_code=404, detail="privacy_subject_not_found")
            tuple_obj = crypto.identity_tuple_from_value(
                subject_id,
                body.tuple_type,
                body.value,
                label=body.label,
            )
            tuple_id = await insert_identity_tuple(conn, tuple_obj)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="privacy_identity_tuple_invalid",
        ) from exc

    return IdentityTupleCreateOut(
        subject_id=subject_id,
        identity_tuple_id=tuple_id,
        tuple_type=body.tuple_type,
        key_version=crypto.digest_key_version,
        inserted=tuple_id is not None,
    )


@router.post(
    "/subjects/{subject_id}/case-drafts",
    response_model=CaseDraftCreateOut,
)
async def create_privacy_case_draft(
    request: Request,
    subject_id: UUID,
    body: CaseDraftCreateIn,
    user_id: str = Depends(require_auth),
) -> CaseDraftCreateOut:
    _assert_adult_or_admin_actor(request)
    crypto = _load_crypto_or_503()

    try:
        async with rls_connection(request) as conn:
            result = await PrivacyCaseDraftRepository(
                conn,
                crypto,
            ).create_case_draft(
                user_id=user_id,
                subject_id=subject_id,
                target_ids=tuple(body.target_ids),
            )
    except PrivacyDraftSubjectNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="privacy_subject_not_found",
        ) from exc
    except PrivacyDraftTargetNotFound as exc:
        raise HTTPException(
            status_code=400,
            detail="privacy_target_not_found",
        ) from exc
    except PrivacyDraftError as exc:
        raise HTTPException(
            status_code=400,
            detail="privacy_case_draft_invalid",
        ) from exc

    return _case_draft_out(subject_id, result)


@router.get("/case-drafts", response_model=CaseDraftListOut)
async def list_privacy_case_drafts(
    request: Request,
    limit: int = 25,
    _: str = Depends(require_auth),
) -> CaseDraftListOut:
    _assert_adult_or_admin_actor(request)
    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=400,
            detail="privacy_case_draft_limit_invalid",
        )
    crypto = _load_crypto_or_503()

    async with rls_connection(request) as conn:
        drafts = await PrivacyCaseDraftRepository(conn, crypto).list_case_drafts(
            limit=limit,
        )

    return CaseDraftListOut(
        count=len(drafts),
        drafts=[_case_draft_summary_out(item) for item in drafts],
    )


@router.get("/actions/approved", response_model=ApprovedPrivacyActionsOut)
async def list_privacy_approved_actions(
    request: Request,
    limit: int = 25,
    _: str = Depends(require_auth),
) -> ApprovedPrivacyActionsOut:
    _assert_adult_or_admin_actor(request)
    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=400,
            detail="privacy_approved_action_limit_invalid",
        )

    async with rls_connection(request) as conn:
        actions = await list_approved_privacy_actions(conn, limit=limit)

    return ApprovedPrivacyActionsOut(
        count=len(actions),
        actions=[_approved_privacy_action_out(action) for action in actions],
    )


@router.post(
    "/actions/{action_id}/manual-disposition",
    response_model=PrivacyActionWorkflowOut,
)
async def record_privacy_action_manual_disposition(
    request: Request,
    action_id: UUID,
    body: PrivacyActionManualDispositionIn,
    user_id: str = Depends(require_auth),
) -> PrivacyActionWorkflowOut:
    _assert_adult_or_admin_actor(request)
    crypto = _load_crypto_or_503()

    try:
        async with rls_connection(request) as conn:
            result = await PrivacyActionWorkflowRepository(
                conn,
                crypto,
            ).record_manual_disposition(
                action_id=action_id,
                actor=user_id,
                disposition=body.disposition,
                operator_note=body.operator_note,
                evidence_reference=body.evidence_reference,
                verification_due_at=body.verification_due_at,
            )
    except PrivacyActionWorkflowNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="privacy_action_not_found",
        ) from exc
    except PrivacyActionWorkflowError as exc:
        raise HTTPException(
            status_code=409,
            detail="privacy_action_workflow_invalid",
        ) from exc

    return _privacy_action_workflow_out(result)


@router.post(
    "/actions/{action_id}/verification",
    response_model=PrivacyActionWorkflowOut,
)
async def record_privacy_action_verification(
    request: Request,
    action_id: UUID,
    body: PrivacyActionVerificationIn,
    user_id: str = Depends(require_auth),
) -> PrivacyActionWorkflowOut:
    _assert_adult_or_admin_actor(request)
    crypto = _load_crypto_or_503()

    try:
        async with rls_connection(request) as conn:
            result = await PrivacyActionWorkflowRepository(
                conn,
                crypto,
            ).record_verification(
                action_id=action_id,
                actor=user_id,
                outcome=body.outcome,
                operator_note=body.operator_note,
                evidence_reference=body.evidence_reference,
                verification_due_at=body.verification_due_at,
            )
    except PrivacyActionWorkflowNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="privacy_action_not_found",
        ) from exc
    except PrivacyActionWorkflowError as exc:
        raise HTTPException(
            status_code=409,
            detail="privacy_action_workflow_invalid",
        ) from exc

    return _privacy_action_workflow_out(result)


@router.get(
    "/case-drafts/{case_id}/timeline",
    response_model=PrivacyCaseTimelineOut,
)
async def get_privacy_case_timeline(
    request: Request,
    case_id: UUID,
    _: str = Depends(require_auth),
) -> PrivacyCaseTimelineOut:
    _assert_adult_or_admin_actor(request)

    try:
        async with rls_connection(request) as conn:
            result = await PrivacyCaseWorkflowReader(conn).get_timeline(case_id)
    except PrivacyActionWorkflowNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="privacy_case_draft_not_found",
        ) from exc

    return _privacy_case_timeline_out(result)


@router.get(
    "/case-drafts/{case_id}/report",
    response_model=PrivacyCaseReportOut,
)
async def get_privacy_case_report(
    request: Request,
    case_id: UUID,
    _: str = Depends(require_auth),
) -> PrivacyCaseReportOut:
    _assert_adult_or_admin_actor(request)

    try:
        async with rls_connection(request) as conn:
            result = await PrivacyCaseWorkflowReader(conn).get_report(case_id)
    except PrivacyActionWorkflowNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="privacy_case_draft_not_found",
        ) from exc

    return _privacy_case_report_out(result)


@router.get("/case-drafts/{case_id}", response_model=CaseDraftDetailOut)
async def get_privacy_case_draft(
    request: Request,
    case_id: UUID,
    _: str = Depends(require_auth),
) -> CaseDraftDetailOut:
    _assert_adult_or_admin_actor(request)
    crypto = _load_crypto_or_503()

    try:
        async with rls_connection(request) as conn:
            result = await PrivacyCaseDraftRepository(conn, crypto).get_case_draft(
                case_id,
            )
    except PrivacyDraftCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="privacy_case_draft_not_found",
        ) from exc
    except PrivacyDraftError as exc:
        raise HTTPException(
            status_code=500,
            detail="privacy_case_draft_unavailable",
        ) from exc

    return _case_draft_detail_out(result)


@router.post(
    "/case-drafts/{case_id}/submit-approval",
    response_model=CaseDraftDispositionOut,
)
async def submit_privacy_case_draft_for_approval(
    request: Request,
    case_id: UUID,
    body: CaseDraftDispositionIn,
    user_id: str = Depends(require_auth),
) -> CaseDraftDispositionOut:
    _assert_adult_or_admin_actor(request)
    crypto = _load_crypto_or_503()
    actor_type = getattr(request.state, "actor_type", "user")

    try:
        async with rls_connection(request) as conn:
            result = await PrivacyCaseDraftRepository(
                conn,
                crypto,
            ).submit_case_draft_for_approval(
                case_id=case_id,
                user_id=user_id,
                actor_type=actor_type,
                operator_note=body.operator_note,
            )
    except PrivacyDraftCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="privacy_case_draft_not_found",
        ) from exc
    except PrivacyDraftDispositionError as exc:
        raise HTTPException(
            status_code=409,
            detail="privacy_case_draft_disposition_invalid",
        ) from exc
    except PrivacyDraftError as exc:
        raise HTTPException(
            status_code=500,
            detail="privacy_case_draft_unavailable",
        ) from exc

    return _case_draft_disposition_out(result)


@router.post(
    "/case-drafts/{case_id}/archive",
    response_model=CaseDraftDispositionOut,
)
async def archive_privacy_case_draft(
    request: Request,
    case_id: UUID,
    body: CaseDraftDispositionIn,
    user_id: str = Depends(require_auth),
) -> CaseDraftDispositionOut:
    _assert_adult_or_admin_actor(request)
    crypto = _load_crypto_or_503()

    try:
        async with rls_connection(request) as conn:
            result = await PrivacyCaseDraftRepository(conn, crypto).archive_case_draft(
                case_id=case_id,
                user_id=user_id,
                operator_note=body.operator_note,
            )
    except PrivacyDraftCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="privacy_case_draft_not_found",
        ) from exc
    except PrivacyDraftDispositionError as exc:
        raise HTTPException(
            status_code=409,
            detail="privacy_case_draft_disposition_invalid",
        ) from exc
    except PrivacyDraftError as exc:
        raise HTTPException(
            status_code=500,
            detail="privacy_case_draft_unavailable",
        ) from exc

    return _case_draft_disposition_out(result)


@router.get("/targets", response_model=PrivacyTargetsOut)
async def list_privacy_targets(
    request: Request,
    _: str = Depends(require_auth),
) -> PrivacyTargetsOut:
    _assert_adult_or_admin_actor(request)
    async with rls_connection(request) as conn:
        targets = await list_targets(conn)

    return PrivacyTargetsOut(
        count=len(targets),
        targets=[PrivacyTargetOut(**target) for target in targets],
    )


@router.post("/targets/refresh", response_model=PrivacyTargetsRefreshOut)
async def refresh_privacy_targets(
    request: Request,
    _: str = Depends(require_auth),
) -> PrivacyTargetsRefreshOut:
    _assert_adult_or_admin_actor(request)
    source_label = "bundled_yaml"
    try:
        targets = load_all_targets()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="privacy_targets_registry_invalid",
        ) from exc

    async with rls_connection(request) as conn:
        count = await refresh_targets_cache(conn, targets, source_label=source_label)

    return PrivacyTargetsRefreshOut(count=count, source_label=source_label)


def _assert_adult_or_admin_actor(request: Request) -> None:
    actor_type = getattr(request.state, "actor_type", "user")
    role = getattr(request.state, "role", "user")
    if actor_type != "user" or role == "child":
        raise HTTPException(status_code=403, detail="privacy_intake_forbidden")


def _guardian_user_id(user_id: str, body: SubjectCreateIn) -> str | None:
    if body.role == Role.ADULT:
        if body.guardian_user_id is not None:
            raise HTTPException(
                status_code=400,
                detail="privacy_adult_subject_cannot_have_guardian",
            )
        return None
    if body.guardian_user_id is not None and body.guardian_user_id != user_id:
        raise HTTPException(
            status_code=400,
            detail="privacy_guardian_must_be_authenticated_user",
        )
    return user_id


def _identity_tuple_input(item: IdentityTupleIn) -> IdentityTupleInput:
    return IdentityTupleInput(
        tuple_type=item.tuple_type,
        raw_value=item.value,
        label=item.label,
    )


def _case_draft_out(
    subject_id: UUID,
    result: CreatedCaseDraft,
) -> CaseDraftCreateOut:
    return CaseDraftCreateOut(
        case_id=result.case_draft.id,
        subject_id=subject_id,
        status=result.case_draft.status,
        target_count=result.case_draft.target_count,
        action_count=len(result.actions),
        payload_key_version=result.case_draft.payload_key_version,
        review_packets=[_review_packet_out(packet) for packet in result.review_packets],
        actions=[
            DraftActionOut(
                action_id=action.id,
                target_id=action.target_id,
                approval_tier=action.approval_tier,
                status=action.status,
            )
            for action in result.actions
        ],
    )


def _case_draft_summary_out(item: CaseDraftInboxItem) -> CaseDraftSummaryOut:
    draft = item.case_draft
    return CaseDraftSummaryOut(
        case_id=draft.id,
        subject_id=draft.subject_id,
        status=draft.status,
        target_count=draft.target_count,
        action_count=item.action_count,
        highest_approval_tier=item.highest_approval_tier,
        payload_key_version=draft.payload_key_version,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _approved_privacy_action_out(
    action: StoredApprovedPrivacyAction,
) -> ApprovedPrivacyActionOut:
    return ApprovedPrivacyActionOut(
        action_id=action.id,
        case_id=action.case_draft_id,
        subject_id=action.subject_id,
        target_id=action.target_id,
        target_name=action.target_name,
        category=action.target_category,
        jurisdiction=action.target_jurisdiction,
        opt_out_method=action.target_opt_out_method,
        approval_tier=action.approval_tier,
        status=action.status,
        approval_queue_id=action.approval_queue_id,
        case_status=action.case_status,
        manual_disposition=action.manual_disposition,
        manual_disposition_at=action.manual_disposition_at,
        manual_disposition_by=action.manual_disposition_by,
        manual_note_hash=action.manual_note_hash,
        evidence_payload_hash=action.evidence_payload_hash,
        workflow_payload_key_version=action.workflow_payload_key_version,
        sent_at=action.sent_at,
        confirmed_at=action.confirmed_at,
        verification_due_at=action.verification_due_at,
        error_code=action.error_code,
        error_digest=action.error_digest,
        approved_at=action.approved_at,
        created_at=action.created_at,
        updated_at=action.updated_at,
        avg_response_days=action.target_avg_response_days,
    )


def _privacy_action_workflow_out(
    result: PrivacyActionWorkflowResult,
) -> PrivacyActionWorkflowOut:
    return PrivacyActionWorkflowOut(
        event_type=result.event_type,
        action=_approved_privacy_action_out(result.action),
    )


def _privacy_case_timeline_out(
    result: PrivacyCaseTimeline,
) -> PrivacyCaseTimelineOut:
    return PrivacyCaseTimelineOut(
        case_id=result.case_draft.id,
        subject_id=result.case_draft.subject_id,
        status=result.case_draft.status,
        event_count=len(result.events),
        events=[_privacy_case_event_out(event) for event in result.events],
    )


def _privacy_case_report_out(
    result: PrivacyCaseReport,
) -> PrivacyCaseReportOut:
    return PrivacyCaseReportOut(
        case_id=result.case_draft.id,
        subject_id=result.case_draft.subject_id,
        status=result.case_draft.status,
        target_count=result.case_draft.target_count,
        action_count=len(result.actions),
        event_count=len(result.events),
        generated_at=result.generated_at,
        actions=[_approved_privacy_action_out(action) for action in result.actions],
        events=[_privacy_case_event_out(event) for event in result.events],
        evidence_manifest=_privacy_evidence_manifest_out(result),
    )


@router.get(
    "/removal-control/summary",
    response_model=PrivacyRemovalControlSummaryOut,
)
async def get_privacy_removal_control_summary(
    request: Request,
    _: str = Depends(require_auth),
) -> PrivacyRemovalControlSummaryOut:
    _assert_adult_or_admin_actor(request)
    async with rls_connection(request) as conn:
        summary = await PrivacyRemovalControlRepository(conn).summary()

    return _privacy_removal_control_summary_out(summary)


@router.post(
    "/subjects/{subject_id}/removal-control/seed",
    response_model=PrivacyRemovalSeedOut,
)
async def seed_privacy_removal_control(
    request: Request,
    subject_id: UUID,
    body: PrivacyRemovalSeedIn,
    user_id: str = Depends(require_auth),
) -> PrivacyRemovalSeedOut:
    _assert_adult_or_admin_actor(request)
    crypto = _load_crypto_or_503()

    try:
        async with rls_connection(request) as conn:
            result = await PrivacyRemovalControlSeedRepository(
                conn,
                crypto,
            ).seed_subject(
                subject_id=subject_id,
                actor=user_id,
                confirmed_authorization=body.confirmed_authorization,
            )
    except PrivacyRemovalSeedSubjectNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="privacy_subject_not_found",
        ) from exc
    except PrivacyRemovalSeedTargetMissing as exc:
        raise HTTPException(
            status_code=409,
            detail="privacy_targets_cache_empty",
        ) from exc
    except PrivacyRemovalSeedError as exc:
        raise HTTPException(
            status_code=400,
            detail="privacy_removal_seed_invalid",
        ) from exc

    return _privacy_removal_seed_out(result)


def _privacy_evidence_manifest_out(
    result: PrivacyCaseReport,
) -> PrivacyEvidenceManifestOut:
    terminal_statuses = {"confirmed", "failed"}
    handled_statuses = {"sent", "confirmed", "failed"}
    terminal_action_count = sum(
        1 for action in result.actions if action.status in terminal_statuses
    )
    open_action_count = len(result.actions) - terminal_action_count
    missing_evidence_count = sum(
        1
        for action in result.actions
        if action.status in handled_statuses and not action.evidence_payload_hash
    )
    status: Literal["complete", "attention"] = (
        "complete"
        if open_action_count == 0 and missing_evidence_count == 0
        else "attention"
    )
    return PrivacyEvidenceManifestOut(
        status=status,
        action_count=len(result.actions),
        terminal_action_count=terminal_action_count,
        open_action_count=open_action_count,
        manual_note_hash_count=sum(
            1 for action in result.actions if action.manual_note_hash
        ),
        evidence_payload_hash_count=sum(
            1 for action in result.actions if action.evidence_payload_hash
        ),
        event_payload_hash_count=sum(
            1 for event in result.events if event.event_payload_hash
        ),
        missing_evidence_count=missing_evidence_count,
    )


def _privacy_case_event_out(event: StoredPrivacyActionEvent) -> PrivacyCaseEventOut:
    return PrivacyCaseEventOut(
        event_id=event.id,
        action_id=event.action_id,
        case_id=event.case_draft_id,
        target_id=event.target_id,
        target_name=event.target_name,
        event_type=event.event_type,
        actor=event.actor,
        event_payload_hash=event.event_payload_hash,
        created_at=event.created_at,
    )


def _privacy_removal_control_summary_out(
    summary: RemovalControlSummary,
) -> PrivacyRemovalControlSummaryOut:
    return PrivacyRemovalControlSummaryOut(
        generated_at=summary.generated_at,
        mode=summary.mode,
        outbound_enabled=summary.outbound_enabled,
        counts=PrivacyRemovalCountsOut(**asdict(summary.counts)),
        lanes=[_privacy_removal_lane_out(lane) for lane in summary.lanes],
        lenses=[_privacy_removal_lens_out(lens) for lens in summary.lenses],
        benchmarks=[
            _privacy_removal_benchmark_out(benchmark)
            for benchmark in summary.benchmarks
        ],
    )


def _privacy_removal_seed_out(
    result: RemovalControlSeedResult,
) -> PrivacyRemovalSeedOut:
    counts = result.counts
    return PrivacyRemovalSeedOut(
        subject_id=result.subject_id,
        broker_target_id=result.broker_target_id,
        public_record_target_id=result.public_record_target_id,
        payload_key_version=result.payload_key_version,
        generated_at=result.generated_at,
        counts=PrivacyRemovalSeedCountsOut(
            authorizations_created=counts.authorizations_created,
            authorizations_skipped=counts.authorizations_skipped,
            evidence_created=counts.evidence_created,
            evidence_skipped=counts.evidence_skipped,
            monitor_runs_created=counts.monitor_runs_created,
            monitor_runs_skipped=counts.monitor_runs_skipped,
            search_deindex_created=counts.search_deindex_created,
            search_deindex_skipped=counts.search_deindex_skipped,
            public_record_triage_created=counts.public_record_triage_created,
            public_record_triage_skipped=counts.public_record_triage_skipped,
            total_created=counts.total_created,
            total_skipped=counts.total_skipped,
        ),
    )


def _privacy_removal_lane_out(lane: RemovalLane) -> PrivacyRemovalLaneOut:
    return PrivacyRemovalLaneOut(
        code=lane.code,
        label=lane.label,
        status=lane.status,
        north_star=lane.north_star,
        current_state=lane.current_state,
        next_step=lane.next_step,
        evidence_key=lane.evidence_key,
        metric=lane.metric,
    )


def _privacy_removal_lens_out(lens: RemovalLens) -> PrivacyRemovalLensOut:
    return PrivacyRemovalLensOut(
        code=lens.code,
        label=lens.label,
        status=lens.status,
        summary=lens.summary,
        checkpoints=list(lens.checkpoints),
    )


def _privacy_removal_benchmark_out(
    benchmark: RemovalBenchmark,
) -> PrivacyRemovalBenchmarkOut:
    return PrivacyRemovalBenchmarkOut(
        provider=benchmark.provider,
        capability=benchmark.capability,
        alpha_gap=benchmark.alpha_gap,
        control=benchmark.control,
    )


def _case_draft_detail_out(result: RetrievedCaseDraft) -> CaseDraftDetailOut:
    item = CaseDraftInboxItem(
        case_draft=result.case_draft,
        action_count=len(result.actions),
        approval_tiers=tuple(
            sorted({action.approval_tier for action in result.actions})
        ),
    )
    summary = _case_draft_summary_out(item)
    return CaseDraftDetailOut(
        **summary.model_dump(),
        review_packets=[_review_packet_out(packet) for packet in result.review_packets],
        actions=[
            DraftActionOut(
                action_id=action.id,
                target_id=action.target_id,
                approval_tier=action.approval_tier,
                status=action.status,
            )
            for action in result.actions
        ],
    )


def _case_draft_disposition_out(
    result: CaseDraftDisposition,
) -> CaseDraftDispositionOut:
    return CaseDraftDispositionOut(
        case_id=result.case_draft.id,
        status=result.case_draft.status,
        disposition=result.disposition,
        action_count=len(result.actions),
        highest_approval_tier=result.highest_approval_tier,
        queue_id=result.approval_queue_id,
    )


def _review_packet_out(packet: TargetReviewPacket) -> TargetReviewPacketOut:
    return TargetReviewPacketOut(
        target_id=packet.target_id,
        target_name=packet.target_name,
        category=packet.category,
        jurisdiction=packet.jurisdiction,
        opt_out_method=packet.opt_out_method,
        approval_tier=packet.approval_tier,
        approval_reason=packet.approval_reason,
        legal_basis=packet.legal_basis,
        required_identifiers=list(packet.required_identifiers),
        available_identity_tuple_types=list(packet.available_identity_tuple_types),
        evidence_checklist=list(packet.evidence_checklist),
        risk_flags=list(packet.risk_flags),
    )


def _load_crypto_or_503() -> PrivacyCrypto:
    try:
        return load_privacy_crypto()
    except PrivacyScrubConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail="privacy_scrub_config_missing",
        ) from exc
