"""Identity and personal-data settings for Alpha."""

from __future__ import annotations

from datetime import date, datetime
import json
import re
from typing import Any, Literal
from uuid import UUID

import asyncpg
from pydantic import BaseModel, ConfigDict, Field, field_validator

from jarvis_common.secrets import get_secret

ProfileRole = Literal["admin", "child"]
MaxRating = Literal["all_ages", "age_8_plus", "teen", "adult"]

PIN_PLACEHOLDER = "PLACEHOLDER_SET_BY_KEN"
PERSONAL_DATA_SETTINGS_ID = 1
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_DIGIT_RE = re.compile(r"\D+")


class SettingsIdentityError(RuntimeError):
    """Raised when identity settings cannot be saved."""


class ProfilePersonalDataIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    legal_name: str | None = Field(default=None, max_length=160)
    preferred_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    birthday: date | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "legal_name", "preferred_name", "email", "phone", "notes", mode="before"
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if not EMAIL_RE.fullmatch(normalized):
            raise ValueError("email must look like name@example.com")
        return normalized

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = PHONE_DIGIT_RE.sub("", value)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            raise ValueError("phone must be 10 digits, like 555-555-5555")
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


class ProfilePersonalData(ProfilePersonalDataIn):
    profile_id: str
    updated_at: datetime | None = None
    updated_by_profile_id: str | None = None
    data_classification: Literal["personal_information"] = "personal_information"


class ProfileOut(BaseModel):
    id: str
    display_name: str
    role: ProfileRole
    child_age: int | None = None
    max_rating: MaxRating
    active: bool
    pin_status: Literal["set", "placeholder"]
    personal_data: ProfilePersonalData | None = None


class ProfileCreateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str | None = Field(default=None, min_length=2, max_length=40)
    display_name: str = Field(min_length=1, max_length=120)
    role: ProfileRole
    child_age: int | None = Field(default=None, ge=0, le=17)
    max_rating: MaxRating = "adult"

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower().strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,39}", normalized):
            raise ValueError(
                "id must use lowercase letters, numbers, dash, or underscore"
            )
        return normalized


class RelationshipIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: UUID | None = None
    from_profile_id: str
    to_profile_id: str
    relationship_label: str = Field(min_length=1, max_length=80)
    inverse_relationship_label: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("inverse_relationship_label", "notes", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class RelationshipOut(RelationshipIn):
    id: UUID
    updated_at: datetime | None = None
    updated_by_profile_id: str | None = None
    data_classification: Literal["personal_information"] = "personal_information"


class HomeAddressIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(default="Home", min_length=1, max_length=80)
    line1: str | None = Field(default=None, max_length=160)
    line2: str | None = Field(default=None, max_length=160)
    city: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(default="US", min_length=2, max_length=2)

    @field_validator("line1", "line2", "city", "region", "postal_code", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("country")
    @classmethod
    def _uppercase_country(cls, value: str) -> str:
        return value.upper()


class HomeAddress(HomeAddressIn):
    updated_at: datetime | None = None
    updated_by_profile_id: str | None = None
    data_classification: Literal["personal_information"] = "personal_information"


class PersonalDataSettingsOut(BaseModel):
    home_address: HomeAddress | None = None
    storage_classification: Literal["alpha_db_personal_settings"] = (
        "alpha_db_personal_settings"
    )


class IdentitySettingsOut(BaseModel):
    profiles: list[ProfileOut]
    relationships: list[RelationshipOut]
    personal_data: PersonalDataSettingsOut


def _decode_jsonb(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    if isinstance(value, dict):
        return value
    return {}


def _pin_status(pin_hash: str) -> Literal["set", "placeholder"]:
    if pin_hash == "PLACEHOLDER_MIGRATE_FROM_ALPHA_PIN":
        try:
            get_secret("ALPHA_PIN")
        except KeyError:
            return "placeholder"
        return "set"
    if pin_hash.startswith("PLACEHOLDER"):
        return "placeholder"
    return "set"


def _slug_profile_id(display_name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", display_name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise SettingsIdentityError("display name cannot produce a profile id")
    return slug[:40]


def _personal_data_rows(rows: list[asyncpg.Record]) -> dict[str, ProfilePersonalData]:
    output: dict[str, ProfilePersonalData] = {}
    for row in rows:
        output[row["profile_id"]] = ProfilePersonalData(
            profile_id=row["profile_id"],
            legal_name=row["legal_name"],
            preferred_name=row["preferred_name"],
            email=row["email"],
            phone=row["phone"],
            birthday=row["birthday"],
            notes=row["notes"],
            updated_at=row["updated_at"],
            updated_by_profile_id=row["updated_by_profile_id"],
        )
    return output


def _home_address_from_row(row: asyncpg.Record | None) -> HomeAddress | None:
    if row is None:
        return None
    payload = _decode_jsonb(row["home_address"])
    if not payload:
        return None
    address = HomeAddressIn.model_validate(payload)
    return HomeAddress(
        **address.model_dump(),
        updated_at=row["updated_at"],
        updated_by_profile_id=row["updated_by_profile_id"],
    )


def _relationship_out(row: asyncpg.Record) -> RelationshipOut:
    return RelationshipOut(
        id=row["id"],
        from_profile_id=row["from_profile_id"],
        to_profile_id=row["to_profile_id"],
        relationship_label=row["relationship_label"],
        inverse_relationship_label=row["inverse_relationship_label"],
        notes=row["notes"],
        updated_at=row["updated_at"],
        updated_by_profile_id=row["updated_by_profile_id"],
    )


async def fetch_identity_settings(conn: asyncpg.Connection) -> IdentitySettingsOut:
    profile_rows = await conn.fetch(
        """
        SELECT id, display_name, role, child_age, max_rating, pin_hash, active
        FROM public.alpha_profiles
        WHERE active = true
        ORDER BY
            CASE WHEN role = 'admin' THEN 0 ELSE 1 END,
            CASE id
                WHEN 'ken' THEN 0
                WHEN 'sweta' THEN 1
                WHEN 'ryleigh' THEN 2
                WHEN 'sloane' THEN 3
                ELSE 99
            END,
            display_name
        """
    )
    data_rows = await conn.fetch(
        """
        SELECT profile_id, legal_name, preferred_name, email, phone, birthday,
               notes, updated_at, updated_by_profile_id
        FROM public.alpha_profile_personal_data
        """
    )
    relationships = await conn.fetch(
        """
        SELECT id, from_profile_id, to_profile_id, relationship_label,
               inverse_relationship_label, notes, updated_at, updated_by_profile_id
        FROM public.alpha_profile_relationships
        ORDER BY created_at ASC, id ASC
        """
    )
    home_row = await conn.fetchrow(
        """
        SELECT home_address, updated_at, updated_by_profile_id
        FROM public.alpha_personal_data_settings
        WHERE id = $1
        """,
        PERSONAL_DATA_SETTINGS_ID,
    )

    personal_data = _personal_data_rows(list(data_rows))
    profiles = [
        ProfileOut(
            id=row["id"],
            display_name=row["display_name"],
            role=row["role"],
            child_age=row["child_age"],
            max_rating=row["max_rating"],
            active=row["active"],
            pin_status=_pin_status(row["pin_hash"]),
            personal_data=personal_data.get(row["id"]),
        )
        for row in profile_rows
    ]

    return IdentitySettingsOut(
        profiles=profiles,
        relationships=[_relationship_out(row) for row in relationships],
        personal_data=PersonalDataSettingsOut(
            home_address=_home_address_from_row(home_row)
        ),
    )


async def create_profile(
    conn: asyncpg.Connection,
    request: ProfileCreateIn,
) -> ProfileOut:
    profile_id = request.id or _slug_profile_id(request.display_name)
    if request.role == "child" and request.child_age is None:
        raise SettingsIdentityError("child profiles require child_age")
    child_age = request.child_age if request.role == "child" else None
    max_rating = request.max_rating
    if request.role == "admin":
        max_rating = "adult"

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO public.alpha_profiles
                (id, display_name, role, child_age, max_rating, pin_hash, active)
            VALUES ($1, $2, $3, $4, $5, $6, true)
            RETURNING id, display_name, role, child_age, max_rating, pin_hash, active
            """,
            profile_id,
            request.display_name,
            request.role,
            child_age,
            max_rating,
            PIN_PLACEHOLDER,
        )
    except asyncpg.UniqueViolationError as exc:
        raise SettingsIdentityError(f"profile already exists: {profile_id}") from exc

    return ProfileOut(
        id=row["id"],
        display_name=row["display_name"],
        role=row["role"],
        child_age=row["child_age"],
        max_rating=row["max_rating"],
        active=row["active"],
        pin_status="placeholder",
    )


async def save_profile_personal_data(
    conn: asyncpg.Connection,
    profile_id: str,
    payload: ProfilePersonalDataIn,
    *,
    updated_by_profile_id: str,
) -> ProfilePersonalData:
    profile_exists = await conn.fetchval(
        "SELECT true FROM public.alpha_profiles WHERE id = $1 AND active = true",
        profile_id,
    )
    if not profile_exists:
        raise SettingsIdentityError(f"profile not found: {profile_id}")

    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_profile_personal_data
            (profile_id, legal_name, preferred_name, email, phone, birthday,
             notes, updated_by_profile_id, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
        ON CONFLICT (profile_id) DO UPDATE
        SET legal_name = EXCLUDED.legal_name,
            preferred_name = EXCLUDED.preferred_name,
            email = EXCLUDED.email,
            phone = EXCLUDED.phone,
            birthday = EXCLUDED.birthday,
            notes = EXCLUDED.notes,
            updated_by_profile_id = EXCLUDED.updated_by_profile_id,
            updated_at = now()
        RETURNING profile_id, legal_name, preferred_name, email, phone, birthday,
                  notes, updated_at, updated_by_profile_id
        """,
        profile_id,
        payload.legal_name,
        payload.preferred_name,
        payload.email,
        payload.phone,
        payload.birthday,
        payload.notes,
        updated_by_profile_id,
    )
    return _personal_data_rows([row])[profile_id]


async def save_relationship(
    conn: asyncpg.Connection,
    payload: RelationshipIn,
    *,
    updated_by_profile_id: str,
) -> RelationshipOut:
    if payload.from_profile_id == payload.to_profile_id:
        raise SettingsIdentityError("relationship profiles must be different")
    for profile_id in (payload.from_profile_id, payload.to_profile_id):
        profile_exists = await conn.fetchval(
            "SELECT true FROM public.alpha_profiles WHERE id = $1 AND active = true",
            profile_id,
        )
        if not profile_exists:
            raise SettingsIdentityError(f"profile not found: {profile_id}")

    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_profile_relationships
            (id, from_profile_id, to_profile_id, relationship_label,
             inverse_relationship_label, notes, updated_by_profile_id, updated_at)
        VALUES (COALESCE($1, gen_random_uuid()), $2, $3, $4, $5, $6, $7, now())
        ON CONFLICT (from_profile_id, to_profile_id) DO UPDATE
        SET relationship_label = EXCLUDED.relationship_label,
            inverse_relationship_label = EXCLUDED.inverse_relationship_label,
            notes = EXCLUDED.notes,
            updated_by_profile_id = EXCLUDED.updated_by_profile_id,
            updated_at = now()
        RETURNING id, from_profile_id, to_profile_id, relationship_label,
                  inverse_relationship_label, notes, updated_at, updated_by_profile_id
        """,
        payload.id,
        payload.from_profile_id,
        payload.to_profile_id,
        payload.relationship_label,
        payload.inverse_relationship_label,
        payload.notes,
        updated_by_profile_id,
    )
    return _relationship_out(row)


async def delete_relationship(conn: asyncpg.Connection, relationship_id: UUID) -> bool:
    result = await conn.execute(
        "DELETE FROM public.alpha_profile_relationships WHERE id = $1",
        relationship_id,
    )
    return result.endswith(" 1")


async def save_home_address(
    conn: asyncpg.Connection,
    payload: HomeAddressIn,
    *,
    updated_by_profile_id: str,
) -> PersonalDataSettingsOut:
    encoded = json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        separators=(",", ":"),
    )
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_personal_data_settings
            (id, home_address, updated_by_profile_id, updated_at)
        VALUES ($1, $2::jsonb, $3, now())
        ON CONFLICT (id) DO UPDATE
        SET home_address = EXCLUDED.home_address,
            updated_by_profile_id = EXCLUDED.updated_by_profile_id,
            updated_at = now()
        RETURNING home_address, updated_at, updated_by_profile_id
        """,
        PERSONAL_DATA_SETTINGS_ID,
        encoded,
        updated_by_profile_id,
    )
    return PersonalDataSettingsOut(home_address=_home_address_from_row(row))
