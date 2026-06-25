"""Helpers for Alpha's vendored external data-source registry."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml

from brain.registry.models import SkillManifestV1, SkillSpec

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_SOURCE_REGISTRY_ROOT = REPO_ROOT / "vendor" / "jarvis-data-sources"
LOCAL_DATA_SOURCE_REGISTRY_ROOT = REPO_ROOT.parent / "jarvis-data-sources"

ACTIVE_GATEWAY_EXTERNAL_DATA_DOMAINS = frozenset(
    {
        "financial",
        "financial-market",
        "geo",
        "medical",
        "medical-reference",
        "news",
        "productivity-comms",
        "scholarly-reference",
        "security-intel",
        "utility",
        "weather",
        "web-search",
    }
)

EXTERNAL_DATA_DOMAINS_BY_SKILL_DOMAIN = {
    "internet_scout": frozenset(
        {
            "financial-market",
            "medical-reference",
            "news",
            "productivity-comms",
            "scholarly-reference",
            "security-intel",
            "web-search",
        }
    ),
}


@dataclass(frozen=True)
class DataSourceEntry:
    """Compact projection of one jarvis-data-sources registry entry."""

    id: str
    name: str
    domain: str
    url: str
    api_base_url: str | None
    auth_type: str
    pricing: str
    phi_safe: bool
    last_verified: date
    raw: Mapping[str, Any]

    @classmethod
    def from_mapping(
        cls, entry: Mapping[str, Any], *, source_path: Path
    ) -> "DataSourceEntry":
        try:
            entry_id = _required_str(entry, "id")
            raw_verified = entry["last_verified"]
        except KeyError as exc:
            raise ValueError(
                f"{source_path}: missing required field {exc.args[0]!r}"
            ) from exc

        if isinstance(raw_verified, date):
            last_verified = raw_verified
        else:
            last_verified = date.fromisoformat(str(raw_verified))

        auth = entry.get("auth")
        if not isinstance(auth, Mapping):
            raise ValueError(f"{source_path}: {entry_id} auth must be a mapping")

        return cls(
            id=entry_id,
            name=_required_str(entry, "name"),
            domain=_required_str(entry, "domain"),
            url=_required_str(entry, "url"),
            api_base_url=entry.get("api_base_url"),
            auth_type=_required_str(auth, "type"),
            pricing=_required_str(entry, "pricing"),
            phi_safe=bool(entry.get("phi_safe", False)),
            last_verified=last_verified,
            raw=dict(entry),
        )


def load_data_source_registry(
    root: Path | str | None = None,
) -> dict[str, DataSourceEntry]:
    """Load vendored jarvis-data-sources entries keyed by stable source id."""

    registry_root = _resolve_registry_root(root)
    registry_dir = (
        registry_root
        if registry_root.name == "registry"
        else registry_root / "registry"
    )
    if not registry_dir.is_dir():
        raise FileNotFoundError(f"data-source registry not found: {registry_dir}")

    data_sources: dict[str, DataSourceEntry] = {}
    for source_path in sorted(registry_dir.glob("*.yaml")):
        parsed = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, list):
            raise ValueError(f"{source_path}: expected a list of registry entries")
        for raw_entry in parsed:
            if not isinstance(raw_entry, Mapping):
                raise ValueError(f"{source_path}: registry entry must be a mapping")
            entry = DataSourceEntry.from_mapping(raw_entry, source_path=source_path)
            if entry.id in data_sources:
                raise ValueError(f"duplicate data-source id: {entry.id}")
            data_sources[entry.id] = entry

    return data_sources


def evaluate_skill_data_source_coverage(
    skills: tuple[SkillSpec, ...] | list[SkillSpec],
    data_sources: Mapping[str, DataSourceEntry],
) -> list[str]:
    """Return coverage gaps for active Gateway external-data skills."""

    gaps: list[str] = []
    for skill in skills:
        allowed_domains = _allowed_external_data_domains(skill)
        if allowed_domains is None:
            continue

        manifest = SkillManifestV1.model_validate(skill.metadata["manifest"])
        data_source_ids = _skill_data_source_ids(manifest)
        if not data_source_ids:
            gaps.append(f"{skill.name}: missing manifest.egress data source id")
            continue

        for data_source_id in data_source_ids:
            data_source = data_sources.get(data_source_id)
            if data_source is None:
                gaps.append(f"{skill.name}: unknown data source id {data_source_id!r}")
                continue

            if not _domain_matches_allowed(data_source.domain, allowed_domains):
                gaps.append(
                    f"{skill.name}: data source {data_source_id!r} has domain "
                    f"{data_source.domain!r}, expected one of "
                    f"{sorted(allowed_domains)!r}"
                )

    return gaps


def assert_skill_data_source_coverage(
    skills: tuple[SkillSpec, ...] | list[SkillSpec],
    data_sources: Mapping[str, DataSourceEntry],
) -> None:
    """Assert active external-data skills reference curated registry entries."""

    gaps = evaluate_skill_data_source_coverage(skills, data_sources)
    if gaps:
        formatted = "\n- ".join(gaps)
        raise AssertionError(f"external data-source coverage gaps:\n- {formatted}")


def _resolve_registry_root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root).expanduser()

    configured = os.environ.get("JARVIS_DATA_SOURCES_ROOT")
    if configured:
        return Path(configured).expanduser()

    if DEFAULT_DATA_SOURCE_REGISTRY_ROOT.exists():
        return DEFAULT_DATA_SOURCE_REGISTRY_ROOT
    return LOCAL_DATA_SOURCE_REGISTRY_ROOT


def _allowed_external_data_domains(skill: SkillSpec) -> frozenset[str] | None:
    if skill.status != "active":
        return None

    manifest = SkillManifestV1.model_validate(skill.metadata["manifest"])
    if manifest.egress.mode != "gateway":
        return None

    if manifest.side_effect_class != "read":
        return None

    if skill.domain in ACTIVE_GATEWAY_EXTERNAL_DATA_DOMAINS:
        return frozenset({skill.domain})
    mapped_domains = EXTERNAL_DATA_DOMAINS_BY_SKILL_DOMAIN.get(skill.domain)
    if mapped_domains:
        active_domains = mapped_domains.intersection(
            ACTIVE_GATEWAY_EXTERNAL_DATA_DOMAINS
        )
        if active_domains:
            return frozenset(active_domains)
    return None


def _skill_data_source_ids(manifest: SkillManifestV1) -> list[str]:
    data_source_ids: list[str] = []
    if manifest.egress.data_source_id:
        data_source_ids.append(manifest.egress.data_source_id)
    data_source_ids.extend(manifest.egress.data_source_ids)
    return list(dict.fromkeys(data_source_ids))


def _domain_matches_allowed(
    source_domain: str,
    allowed_domains: frozenset[str],
) -> bool:
    return any(
        source_domain == allowed_domain
        or source_domain.startswith(f"{allowed_domain}-")
        for allowed_domain in allowed_domains
    )


def _required_str(entry: Mapping[str, Any], key: str) -> str:
    value = entry[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value
