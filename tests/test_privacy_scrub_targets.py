"""Tests for the target YAML registry — schema validation + no dupes."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from brain.agents.privacy_scrub.targets import (
    DATA_DIR,
    Jurisdiction,
    OptOutMethod,
    Target,
    TargetCategory,
    load_all_targets,
    load_targets_from_yaml,
)


def test_brokers_yaml_loads():
    targets = load_targets_from_yaml(DATA_DIR / "brokers.yaml")
    assert len(targets) >= 5, "expected at least the seed brokers"
    ids = {t.id for t in targets}
    assert "spokeo" in ids


def test_brokers_all_data_broker_category():
    targets = load_targets_from_yaml(DATA_DIR / "brokers.yaml")
    for t in targets:
        assert t.category == TargetCategory.DATA_BROKER


def test_ga_court_yaml_loads():
    targets = load_targets_from_yaml(DATA_DIR / "ga_court_targets.yaml")
    assert len(targets) >= 1
    for t in targets:
        assert t.category == TargetCategory.PUBLIC_RECORD
        assert t.opt_out_method == OptOutMethod.COURT_MOTION
        assert t.supports_minors is False
        assert t.jurisdiction == Jurisdiction.US_GA


def test_social_targets_yaml_empty_ok():
    """Placeholder file — should load but produce zero targets."""
    targets = load_targets_from_yaml(DATA_DIR / "social_targets.yaml")
    assert targets == []


def test_load_all_targets_no_dupes():
    targets = load_all_targets()
    ids = [t.id for t in targets]
    assert len(ids) == len(set(ids)), f"duplicate target IDs across YAML: {ids}"


def test_load_all_targets_enum_types_valid():
    for t in load_all_targets():
        assert isinstance(t.category, TargetCategory)
        assert isinstance(t.jurisdiction, Jurisdiction)
        assert isinstance(t.opt_out_method, OptOutMethod)


def test_sensitive_target_flags_load(tmp_path: Path):
    path = tmp_path / "sensitive.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "targets": [
                    {
                        "id": "sensitive_broker",
                        "name": "Sensitive Broker",
                        "category": "data_broker",
                        "jurisdiction": "US_FEDERAL",
                        "opt_out_method": "manual_only",
                        "requires_sensitive_payload": True,
                        "requires_identity_document": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    target = load_targets_from_yaml(path)[0]

    assert target.requires_sensitive_payload is True
    assert target.requires_identity_document is True


def test_missing_yaml_raises():
    with pytest.raises(FileNotFoundError):
        load_targets_from_yaml(DATA_DIR / "does_not_exist.yaml")


def test_invalid_yaml_schema_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("not_targets:\n  - foo\n")
    with pytest.raises(ValueError, match="targets"):
        load_targets_from_yaml(bad)


def test_invalid_target_entry_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "targets": [
                    {
                        "id": "x",
                        "name": "x",
                        # category missing
                        "jurisdiction": "US_FEDERAL",
                        "opt_out_method": "email",
                    }
                ]
            }
        )
    )
    with pytest.raises(ValueError):
        load_targets_from_yaml(bad)


def test_target_frozen():
    t = Target(
        id="x",
        name="x",
        category=TargetCategory.DATA_BROKER,
        jurisdiction=Jurisdiction.US_FEDERAL,
        opt_out_method=OptOutMethod.EMAIL,
    )
    with pytest.raises(FrozenInstanceError):
        t.name = "y"  # type: ignore[misc]
