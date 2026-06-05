"""Privacy-scrub intake routes.

These routes only create local encrypted intake records. They do not scrape,
send opt-out actions, call public internet targets, or start runners.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brain.agents.privacy_scrub.config import (
    PrivacyScrubConfigError,
    load_privacy_crypto,
)
from brain.agents.privacy_scrub.crypto import PrivacyCrypto
from brain.agents.privacy_scrub.identity import TupleType
from brain.agents.privacy_scrub.repository import (
    IdentityTupleInput,
    PrivacySubjectRepository,
    SubjectIntake,
)
from brain.agents.privacy_scrub.state import (
    get_subject,
    insert_identity_tuple,
    list_targets,
    refresh_targets_cache,
)
from brain.agents.privacy_scrub.subjects import Role
from brain.agents.privacy_scrub.targets import load_all_targets
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


def _load_crypto_or_503() -> PrivacyCrypto:
    try:
        return load_privacy_crypto()
    except PrivacyScrubConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail="privacy_scrub_config_missing",
        ) from exc
