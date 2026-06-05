"""Subject model — a person whose digital footprint we're managing.

Invariants:
    1. Minors MUST have a guardian_user_id.
       Enforced at construction (__post_init__) AND at the DB CHECK
       constraint (`minor_requires_guardian`). Defense in depth.
    2. Subjects can only be seen by their owning user_id OR their
       guardian_user_id (RLS policy: privacy_subjects_isolation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID


class Role(str, Enum):
    ADULT = "adult"
    MINOR = "minor"


class SubjectStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class Subject:
    """A person tracked by the privacy-scrub agent.

    Attributes:
        id: UUID from DB.
        user_id: The admin user who owns this record (RLS principal).
        display_name: Free-form label, e.g. "Ken", "Ryleigh".
        role: ADULT or MINOR.
        guardian_user_id: REQUIRED if role == MINOR. The adult who
            authorizes actions on behalf of the minor.
        dob: Optional date of birth (used for matching only).
        jurisdiction: Default US_GA; informs tax/legal modules.
        status: active | paused | archived.
        notes: Free-form operator notes.
    """

    id: UUID
    user_id: str
    display_name: str
    role: Role
    jurisdiction: str = "US_GA"
    guardian_user_id: Optional[str] = None
    dob: Optional[date] = None
    status: SubjectStatus = SubjectStatus.ACTIVE
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.role == Role.MINOR and not self.guardian_user_id:
            raise ValueError(
                f"Subject {self.display_name!r} is a minor but has no "
                "guardian_user_id — guardian linkage is required."
            )

    @property
    def is_minor(self) -> bool:
        return self.role == Role.MINOR

    @property
    def is_adult(self) -> bool:
        return self.role == Role.ADULT
