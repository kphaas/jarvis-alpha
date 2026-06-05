"""Target registry — data brokers, social platforms, public-record systems,
breach databases. Loaded from YAML files in data/.

The DB table `alpha_privacy_targets_cache` is a materialized mirror of
these YAML files, rebuilt at boot + nightly. YAML is the source of truth;
the cache exists only so we can JOIN against discoveries/actions cheaply.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml


class TargetCategory(str, Enum):
    DATA_BROKER = "data_broker"
    SOCIAL = "social"
    PUBLIC_RECORD = "public_record"
    BREACH_DB = "breach_db"


class OptOutMethod(str, Enum):
    EMAIL = "email"
    WEB_FORM = "web_form"
    API = "api"
    MANUAL_ONLY = "manual_only"
    COURT_MOTION = "court_motion"


class Jurisdiction(str, Enum):
    US_FEDERAL = "US_FEDERAL"
    US_GA = "US_GA"
    GLOBAL = "GLOBAL"


@dataclass(frozen=True, slots=True)
class Target:
    id: str
    name: str
    category: TargetCategory
    jurisdiction: Jurisdiction
    opt_out_method: OptOutMethod
    opt_out_url: Optional[str] = None
    contact_email: Optional[str] = None
    supports_minors: bool = False
    requires_sensitive_payload: bool = False
    requires_identity_document: bool = False
    avg_response_days: Optional[int] = None
    last_verified: Optional[date] = None
    notes: Optional[str] = None


# Directory of YAML registry files. Resolved relative to this module so
# tests can find them without relying on cwd.
DATA_DIR: Path = Path(__file__).parent / "data"


def load_targets_from_yaml(yaml_path: Path) -> list[Target]:
    """Load targets from a single YAML file. Raises on schema errors."""
    if not yaml_path.exists():
        raise FileNotFoundError(f"target YAML not found: {yaml_path}")

    raw = yaml.safe_load(yaml_path.read_text())
    if not isinstance(raw, dict) or "targets" not in raw:
        raise ValueError(f"{yaml_path.name}: expected top-level 'targets:' key")

    targets: list[Target] = []
    entries = raw["targets"] or []
    for entry in entries:
        targets.append(_parse_target(entry, source=yaml_path.name))
    return targets


def load_all_targets() -> list[Target]:
    """Load and dedupe targets from every YAML in DATA_DIR."""
    all_targets: list[Target] = []
    for yaml_file in sorted(DATA_DIR.glob("*.yaml")):
        all_targets.extend(load_targets_from_yaml(yaml_file))

    ids = [t.id for t in all_targets]
    if len(ids) != len(set(ids)):
        dupes = sorted(tid for tid, count in Counter(ids).items() if count > 1)
        raise ValueError(f"duplicate target IDs across YAML files: {dupes}")
    return all_targets


# ---------- internal ----------


def _parse_target(entry: dict, source: str) -> Target:
    try:
        return Target(
            id=entry["id"],
            name=entry["name"],
            category=TargetCategory(entry["category"]),
            jurisdiction=Jurisdiction(entry["jurisdiction"]),
            opt_out_method=OptOutMethod(entry["opt_out_method"]),
            opt_out_url=entry.get("opt_out_url"),
            contact_email=entry.get("contact_email"),
            supports_minors=bool(entry.get("supports_minors", False)),
            requires_sensitive_payload=bool(
                entry.get("requires_sensitive_payload", False)
            ),
            requires_identity_document=bool(
                entry.get("requires_identity_document", False)
            ),
            avg_response_days=entry.get("avg_response_days"),
            last_verified=_parse_date(entry.get("last_verified")),
            notes=entry.get("notes"),
        )
    except KeyError as e:
        raise ValueError(f"invalid target entry in {source}: missing key {e}") from e
    except ValueError as e:
        raise ValueError(f"invalid target entry in {source}: {e}") from e


def _parse_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"unparseable date: {value!r}")
