from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import settings_identity
from brain.services.settings_identity import (
    HomeAddressIn,
    ProfileCreateIn,
    ProfilePersonalDataIn,
    RelationshipIn,
    SettingsIdentityError,
    create_profile,
    fetch_identity_settings,
    save_home_address,
    save_profile_personal_data,
    save_relationship,
)


class FakeRow(dict):
    def __getitem__(self, key):
        return self.get(key)


class FakeConn:
    def __init__(self):
        self.fetch_calls = 0
        self.created_profile = None
        self.personal_data = None
        self.relationship = None
        self.home_address = None
        self.relationship_id = uuid4()
        self.existing_profiles = {"ken", "sweta", "ryleigh"}

    async def fetch(self, query, *args):
        self.fetch_calls += 1
        if "FROM public.alpha_profiles" in query:
            return [
                FakeRow(
                    id="ken",
                    display_name="Ken",
                    role="admin",
                    child_age=None,
                    max_rating="adult",
                    pin_hash="hash",
                    active=True,
                ),
                FakeRow(
                    id="ryleigh",
                    display_name="Ryleigh",
                    role="child",
                    child_age=8,
                    max_rating="age_8_plus",
                    pin_hash="PLACEHOLDER_SET_BY_KEN",
                    active=True,
                ),
            ]
        if "FROM public.alpha_profile_personal_data" in query:
            return [
                FakeRow(
                    profile_id="ken",
                    legal_name=None,
                    preferred_name="Ken",
                    email="ken@example.test",
                    phone=None,
                    birthday=None,
                    notes=None,
                    updated_at=datetime(2026, 6, 18, tzinfo=UTC),
                    updated_by_profile_id="ken",
                )
            ]
        if "FROM public.alpha_profile_relationships" in query:
            return [
                FakeRow(
                    id=self.relationship_id,
                    from_profile_id="ken",
                    to_profile_id="ryleigh",
                    relationship_label="father",
                    inverse_relationship_label="daughter",
                    notes=None,
                    updated_at=datetime(2026, 6, 18, tzinfo=UTC),
                    updated_by_profile_id="ken",
                )
            ]
        return []

    async def fetchrow(self, query, *args):
        if "INSERT INTO public.alpha_profiles" in query:
            self.created_profile = args
            return FakeRow(
                id=args[0],
                display_name=args[1],
                role=args[2],
                child_age=args[3],
                max_rating=args[4],
                pin_hash=args[5],
                active=True,
            )
        if "INSERT INTO public.alpha_profile_personal_data" in query:
            self.personal_data = args
            return FakeRow(
                profile_id=args[0],
                legal_name=args[1],
                preferred_name=args[2],
                email=args[3],
                phone=args[4],
                birthday=args[5],
                notes=args[6],
                updated_by_profile_id=args[7],
                updated_at=datetime(2026, 6, 18, tzinfo=UTC),
            )
        if "INSERT INTO public.alpha_profile_relationships" in query:
            self.relationship = args
            return FakeRow(
                id=args[0] or self.relationship_id,
                from_profile_id=args[1],
                to_profile_id=args[2],
                relationship_label=args[3],
                inverse_relationship_label=args[4],
                notes=args[5],
                updated_by_profile_id=args[6],
                updated_at=datetime(2026, 6, 18, tzinfo=UTC),
            )
        if "INSERT INTO public.alpha_personal_data_settings" in query:
            self.home_address = json.loads(args[1])
            return FakeRow(
                home_address=self.home_address,
                updated_by_profile_id=args[2],
                updated_at=datetime(2026, 6, 18, tzinfo=UTC),
            )
        if "FROM public.alpha_personal_data_settings" in query:
            return FakeRow(
                home_address={"label": "Home", "city": "Testville", "country": "US"},
                updated_by_profile_id="ken",
                updated_at=datetime(2026, 6, 18, tzinfo=UTC),
            )
        return None

    async def fetchval(self, _query, *args):
        return args[0] in self.existing_profiles


def _request(*, role="admin", scopes=None):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_id="ken",
            profile_id="ken",
            role=role,
            actor_type="user",
            scopes=scopes if scopes is not None else ["*"],
        )
    )


def test_identity_settings_routes_are_classified():
    assert classify_route("GET", "/v1/settings/identity") == [
        "read",
        "security_read",
    ]
    assert classify_route("POST", "/v1/settings/users") == [
        "write",
        "security_write",
    ]
    assert classify_route("PUT", "/v1/settings/users/ken/personal-data") == [
        "write",
        "security_write",
    ]
    assert classify_route("PUT", "/v1/settings/relationships") == [
        "write",
        "security_write",
    ]
    delete_classes = classify_route(
        "DELETE", "/v1/settings/relationships/00000000-0000-0000-0000-000000000001"
    )
    assert delete_classes == ["destructive"]
    assert determine_risk_tier(delete_classes) == "T5"


@pytest.mark.asyncio
async def test_fetch_identity_settings_combines_profiles_relationships_and_home_data():
    response = await fetch_identity_settings(FakeConn())

    assert [profile.id for profile in response.profiles] == ["ken", "ryleigh"]
    assert response.profiles[0].personal_data is not None
    assert response.profiles[0].personal_data.email == "ken@example.test"
    assert response.relationships[0].relationship_label == "father"
    assert response.relationships[0].inverse_relationship_label == "daughter"
    assert response.personal_data.home_address is not None
    assert response.personal_data.home_address.data_classification == (
        "personal_information"
    )


@pytest.mark.asyncio
async def test_create_profile_slug_and_placeholder_pin():
    conn = FakeConn()
    response = await create_profile(
        conn,
        ProfileCreateIn(
            display_name="Test Child",
            role="child",
            child_age=9,
            max_rating="age_8_plus",
        ),
    )

    assert response.id == "test-child"
    assert response.pin_status == "placeholder"
    assert conn.created_profile[:6] == (
        "test-child",
        "Test Child",
        "child",
        9,
        "age_8_plus",
        "PLACEHOLDER_SET_BY_KEN",
    )


@pytest.mark.asyncio
async def test_create_child_profile_requires_age():
    with pytest.raises(SettingsIdentityError):
        await create_profile(
            FakeConn(),
            ProfileCreateIn(display_name="Test Child", role="child"),
        )


@pytest.mark.asyncio
async def test_save_profile_personal_data():
    response = await save_profile_personal_data(
        FakeConn(),
        "ken",
        ProfilePersonalDataIn(
            preferred_name="Ken",
            email="ken@example.test",
            birthday=date(1980, 1, 1),
        ),
        updated_by_profile_id="ken",
    )

    assert response.profile_id == "ken"
    assert response.email == "ken@example.test"
    assert response.data_classification == "personal_information"


def test_profile_personal_data_normalizes_contact_fields():
    payload = ProfilePersonalDataIn(
        email="KEN@EXAMPLE.COM",
        phone="(404) 555-1212",
    )

    assert payload.email == "ken@example.com"
    assert payload.phone == "404-555-1212"


@pytest.mark.parametrize(
    "email", ["ken", "ken@", "@example.com", "ken example@example.com"]
)
def test_profile_personal_data_rejects_invalid_email(email):
    with pytest.raises(ValidationError, match="email must look like name@example.com"):
        ProfilePersonalDataIn(email=email)


@pytest.mark.parametrize("phone", ["555-1212", "abc", "223-456-78901"])
def test_profile_personal_data_rejects_invalid_phone(phone):
    with pytest.raises(ValidationError, match="phone must be 10 digits"):
        ProfilePersonalDataIn(phone=phone)


@pytest.mark.asyncio
async def test_save_relationship():
    response = await save_relationship(
        FakeConn(),
        RelationshipIn(
            from_profile_id="ken",
            to_profile_id="ryleigh",
            relationship_label="father",
            inverse_relationship_label="daughter",
        ),
        updated_by_profile_id="ken",
    )

    assert isinstance(response.id, UUID)
    assert response.relationship_label == "father"
    assert response.inverse_relationship_label == "daughter"


@pytest.mark.asyncio
async def test_save_relationship_rejects_unknown_profile():
    with pytest.raises(SettingsIdentityError, match="profile not found: missing"):
        await save_relationship(
            FakeConn(),
            RelationshipIn(
                from_profile_id="ken",
                to_profile_id="missing",
                relationship_label="guardian",
            ),
            updated_by_profile_id="ken",
        )


@pytest.mark.asyncio
async def test_save_home_address():
    response = await save_home_address(
        FakeConn(),
        HomeAddressIn(
            label="Home",
            line1="1 Test Lane",
            city="Testville",
            region="TS",
            postal_code="12345",
        ),
        updated_by_profile_id="ken",
    )

    assert response.home_address is not None
    assert response.home_address.city == "Testville"
    assert response.home_address.data_classification == "personal_information"


@pytest.mark.asyncio
async def test_identity_settings_route_requires_admin():
    with pytest.raises(HTTPException) as exc:
        await settings_identity.get_identity_settings(
            _request(role="child", scopes=["weather.read"]),
            _user_id="ryleigh",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_identity_settings_route_uses_platform_admin_context(monkeypatch):
    seen = {}

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        seen["source"] = source
        seen["audit_actor"] = audit_actor
        yield FakeConn()

    monkeypatch.setattr(
        settings_identity,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )

    response = await settings_identity.get_identity_settings(_request(), _user_id="ken")

    assert response.profiles
    assert seen == {
        "source": "http",
        "audit_actor": "settings_identity_read:ken",
    }
