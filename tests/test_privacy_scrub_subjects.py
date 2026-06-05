"""Tests for Subject model — guardian invariant is the critical one."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from brain.agents.privacy_scrub.subjects import (
    Role,
    Subject,
    SubjectStatus,
)


def test_adult_no_guardian_ok():
    s = Subject(
        id=uuid4(),
        user_id="ken",
        display_name="Ken",
        role=Role.ADULT,
    )
    assert s.role == Role.ADULT
    assert s.guardian_user_id is None
    assert s.is_adult
    assert not s.is_minor


def test_minor_requires_guardian():
    """The single most important invariant in this module."""
    with pytest.raises(ValueError, match="minor.*no guardian_user_id"):
        Subject(
            id=uuid4(),
            user_id="ken",
            display_name="Ryleigh",
            role=Role.MINOR,
            guardian_user_id=None,
        )


def test_minor_empty_string_guardian_rejected():
    """Empty string is not a guardian — falsy values fail the check."""
    with pytest.raises(ValueError):
        Subject(
            id=uuid4(),
            user_id="ken",
            display_name="Ryleigh",
            role=Role.MINOR,
            guardian_user_id="",
        )


def test_minor_with_guardian_ok():
    s = Subject(
        id=uuid4(),
        user_id="ken",
        display_name="Sloane",
        role=Role.MINOR,
        guardian_user_id="ken",
    )
    assert s.is_minor
    assert s.guardian_user_id == "ken"


def test_default_jurisdiction():
    s = Subject(
        id=uuid4(),
        user_id="ken",
        display_name="Ken",
        role=Role.ADULT,
    )
    assert s.jurisdiction == "US_GA"


def test_default_status():
    s = Subject(
        id=uuid4(),
        user_id="ken",
        display_name="Ken",
        role=Role.ADULT,
    )
    assert s.status == SubjectStatus.ACTIVE


def test_frozen_dataclass_immutable():
    s = Subject(
        id=uuid4(),
        user_id="ken",
        display_name="Ken",
        role=Role.ADULT,
    )
    with pytest.raises(FrozenInstanceError):
        s.user_id = "someone_else"  # type: ignore[misc]
