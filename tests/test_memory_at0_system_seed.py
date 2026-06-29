from __future__ import annotations

import json
import subprocess
import sys

from scripts.seed_at0_system_memory_proposals import (
    AT0_SYSTEM_PRINCIPAL,
    AT0_SYSTEM_SEED_VERSION,
    CAPABILITY_NODES,
    DEFAULT_AT0_SYSTEM_APPROVAL_TTL_MINUTES,
    MAX_AT0_SYSTEM_APPROVAL_TTL_MINUTES,
    MIN_AT0_SYSTEM_APPROVAL_TTL_MINUTES,
    build_at0_system_node_proposals,
)


def test_at0_system_seed_builds_reviewed_capability_proposals() -> None:
    proposals = build_at0_system_node_proposals()

    assert len(proposals) == len(CAPABILITY_NODES)
    assert {proposal["principal_id"] for proposal in proposals} == {
        AT0_SYSTEM_PRINCIPAL
    }
    assert {proposal["proposed_action"] for proposal in proposals} == {"create_node"}
    assert {proposal["object_type"] for proposal in proposals} == {"node"}
    assert {proposal["source_surface"] for proposal in proposals} == {"at0_system_seed"}

    labels = {proposal["payload"]["label_preview"] for proposal in proposals}
    assert labels == {
        "Alpha",
        "Helm",
        "Ask",
        "Memory",
        "Spark",
        "Dream",
        "Buddy",
        "Forge",
        "Family",
    }

    first_payload = proposals[0]["payload"]
    assert first_payload["source"] == "explicit"
    assert first_payload["properties"]["domain"] == "at0_system"
    assert first_payload["properties"]["system_principal"] is True
    assert (
        first_payload["properties"]["capability_seed_version"]
        == AT0_SYSTEM_SEED_VERSION
    )
    assert first_payload["properties"]["currentness_policy"] == "candidate_current"
    assert first_payload["provenance"]["contains_raw_profile_scrape"] is False
    assert (
        first_payload["provenance"]["source_basis"]
        == "operator_approved_at0_capability_map"
    )


def test_at0_system_seed_approval_ttl_uses_full_review_window() -> None:
    assert DEFAULT_AT0_SYSTEM_APPROVAL_TTL_MINUTES == 720
    assert (
        MIN_AT0_SYSTEM_APPROVAL_TTL_MINUTES
        <= DEFAULT_AT0_SYSTEM_APPROVAL_TTL_MINUTES
        <= MAX_AT0_SYSTEM_APPROVAL_TTL_MINUTES
    )


def test_at0_system_seed_does_not_include_personal_profile_data() -> None:
    payload_text = json.dumps(build_at0_system_node_proposals()).lower()

    for forbidden in ("resume", "linkedin", "email", "phone", "sweta"):
        assert forbidden not in payload_text


def test_at0_system_seed_cli_previews_json_without_queueing() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/seed_at0_system_memory_proposals.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "preview"
    assert payload["principal_id"] == AT0_SYSTEM_PRINCIPAL
    assert payload["node_count"] == len(CAPABILITY_NODES)


def test_at0_system_seed_cli_rejects_too_short_approval_ttl() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/seed_at0_system_memory_proposals.py",
            "--approval-ttl-minutes",
            "9",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--approval-ttl-minutes must be between" in result.stderr
