"""Encrypted VIP group store contract.

Outbound communication stays fail-closed until the encrypted store can be read
and validated. The module accepts a decrypt callable so the storage backend can
move from file-based `vip_groups.enc` to a vault later without changing routing
logic.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

VIP_GROUPS_ENV = "ALPHA_VIP_GROUPS_PATH"
DEFAULT_VIP_GROUPS_PATH = "~/jarvis/.secrets/vip_groups.enc"
ApprovalTier = Literal["T1", "T2", "T3", "T4", "T5"]


class VipGroupsError(RuntimeError):
    """Base error for fail-closed VIP routing."""


class VipGroupsConfigError(VipGroupsError):
    """The encrypted store is missing, insecure, or malformed."""


class VipGroupPolicy(BaseModel):
    tier: ApprovalTier
    max_per_hour: int | Literal["unlimited"] | None = None
    draft_only: bool = False
    flag_for_review: bool = False
    categories: list[str] = Field(default_factory=list)

    @field_validator("max_per_hour")
    @classmethod
    def validate_max_per_hour(cls, value: int | str | None) -> int | str | None:
        if value is None or value == "unlimited":
            return value
        if isinstance(value, int) and value > 0:
            return value
        raise ValueError("max_per_hour must be positive or unlimited")


class VipMember(BaseModel):
    canonical_id: str = Field(min_length=1, max_length=160)
    handles: dict[str, str] = Field(default_factory=dict)

    @field_validator("canonical_id")
    @classmethod
    def normalize_canonical_id(cls, value: str) -> str:
        return value.strip().lower()


class VipGroup(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=120)
    members: list[VipMember] = Field(default_factory=list)
    policy: VipGroupPolicy

    @field_validator("members", mode="before")
    @classmethod
    def normalize_members(cls, value: Any) -> list[Any]:
        normalized = []
        for member in value or []:
            if isinstance(member, str):
                normalized.append({"canonical_id": member})
            else:
                normalized.append(member)
        return normalized


class VipGroupsConfig(BaseModel):
    version: str = Field(default="v0.9")
    groups: list[VipGroup]

    @model_validator(mode="after")
    def validate_unique_members(self) -> "VipGroupsConfig":
        seen: dict[str, str] = {}
        for group in self.groups:
            for member in group.members:
                if member.canonical_id in seen:
                    raise ValueError(
                        f"VIP member appears in multiple groups: {member.canonical_id}"
                    )
                seen[member.canonical_id] = group.id
        return self

    def policy_for_contact(self, canonical_id: str) -> VipGroupPolicy | None:
        target = canonical_id.strip().lower()
        for group in self.groups:
            if any(member.canonical_id == target for member in group.members):
                return group.policy
        return None


DecryptVipGroups = Callable[[bytes], str]


def resolve_vip_groups_path() -> Path:
    return Path(os.path.expanduser(os.getenv(VIP_GROUPS_ENV, DEFAULT_VIP_GROUPS_PATH)))


def load_vip_groups(
    *,
    path: Path | None = None,
    decrypt: DecryptVipGroups | None = None,
) -> VipGroupsConfig:
    """Load and validate encrypted VIP groups.

    A missing decrypt callable is a configuration error by design. Outbound
    communication code should treat any `VipGroupsError` as "not VIP" and route
    through the approval queue.
    """

    vip_path = path or resolve_vip_groups_path()
    _assert_secret_file(vip_path)
    if decrypt is None:
        raise VipGroupsConfigError("vip_groups decryptor is not configured")

    try:
        plaintext = decrypt(vip_path.read_bytes())
        data = json.loads(plaintext)
        return VipGroupsConfig.model_validate(data)
    except VipGroupsConfigError:
        raise
    except Exception as exc:
        raise VipGroupsConfigError("vip_groups.enc is not readable") from exc


def _assert_secret_file(path: Path) -> None:
    if not path.exists():
        raise VipGroupsConfigError("vip_groups.enc is missing")
    if not path.is_file():
        raise VipGroupsConfigError("vip_groups path is not a file")

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise VipGroupsConfigError("vip_groups.enc must not be group/world readable")
