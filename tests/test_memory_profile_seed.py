from __future__ import annotations

import json
import subprocess
import sys

from scripts.seed_memory_profile_proposals import (
    PROFILE_EDGES,
    PROFILE_NODES,
    PROFILE_SEED_VERSION,
    build_profile_edge_proposals,
    build_profile_node_proposals,
)


def test_profile_seed_builds_reviewed_node_proposals() -> None:
    proposals = build_profile_node_proposals(principal_id="ken")

    assert len(proposals) == len(PROFILE_NODES)
    assert {proposal["proposed_action"] for proposal in proposals} == {"create_node"}
    assert {proposal["object_type"] for proposal in proposals} == {"node"}
    assert {proposal["source_surface"] for proposal in proposals} == {"profile_seed"}
    assert all(proposal["principal_id"] == "ken" for proposal in proposals)

    first_payload = proposals[0]["payload"]
    assert first_payload["source"] == "explicit"
    assert first_payload["properties"]["profile_seed"] is True
    assert first_payload["properties"]["profile_seed_version"] == PROFILE_SEED_VERSION
    assert first_payload["properties"]["currentness_policy"] == "candidate_current"
    assert first_payload["properties"]["refresh_prompt_after_days"] == 180
    assert first_payload["provenance"]["contains_raw_profile_scrape"] is False
    assert (
        first_payload["provenance"]["source_basis"] == "user_approved_profile_context"
    )
    assert {
        proposal["payload"]["provenance"]["source_basis"] for proposal in proposals
    } >= {"resume_docx_and_linkedin_profile", "linkedin_profile", "resume_docx"}


def test_profile_seed_does_not_include_contact_details() -> None:
    proposals = build_profile_node_proposals(principal_id="ken")
    payload_text = json.dumps(proposals).lower()

    for forbidden in ("phone", "email", "@", "cell", "mobile"):
        assert forbidden not in payload_text


def test_profile_edge_seed_requires_approved_endpoint_nodes() -> None:
    proposals, skipped = build_profile_edge_proposals({"nodes": []}, principal_id="ken")

    assert proposals == []
    assert len(skipped) == len(PROFILE_EDGES)
    assert {item["reason"] for item in skipped} == {"missing_active_endpoint_node"}


def test_profile_edge_seed_uses_active_graph_nodes() -> None:
    node_proposals = build_profile_node_proposals(principal_id="ken")
    nodes = [
        {
            "id": f"11111111-1111-4111-8111-{index + 1:012d}",
            "external_ref_type": "profile_seed",
            "external_ref_id": proposal["payload"]["external_ref_id"],
            "label_hash": proposal["payload"]["label_hash"],
            "temporal_state": "active",
        }
        for index, proposal in enumerate(node_proposals)
    ]

    proposals, skipped = build_profile_edge_proposals(
        {"nodes": nodes},
        principal_id="ken",
    )

    assert skipped == []
    assert len(proposals) == len(PROFILE_EDGES)
    assert {proposal["proposed_action"] for proposal in proposals} == {"create_edge"}
    assert {proposal["payload"]["source"] for proposal in proposals} == {"explicit"}
    assert all(proposal["payload"]["from_node_id"] for proposal in proposals)
    assert all(proposal["payload"]["to_node_id"] for proposal in proposals)
    assert all(
        proposal["payload"]["provenance"]["contains_raw_profile_scrape"] is False
        for proposal in proposals
    )


def test_profile_seed_cli_previews_json_without_queueing() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/seed_memory_profile_proposals.py", "--nodes-only"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "preview"
    assert payload["node_count"] == len(PROFILE_NODES)
    assert payload["edge_count"] == 0
