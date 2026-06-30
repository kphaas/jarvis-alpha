from __future__ import annotations

import json
import subprocess
import sys

from scripts.seed_memory_profile_proposals import (
    DEFAULT_PROFILE_SEED_APPROVAL_TTL_MINUTES,
    MAX_PROFILE_SEED_APPROVAL_TTL_MINUTES,
    MIN_PROFILE_SEED_APPROVAL_TTL_MINUTES,
    PROFILE_EDGES,
    PROFILE_NODES,
    PROFILE_SEED_VERSION,
    build_profile_edge_proposals,
    build_profile_node_proposals,
)
from scripts.project_profile_graph_to_semantic import (
    PROFILE_SEMANTIC_SOURCE_ACTION,
    build_profile_semantic_projection,
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


def test_profile_seed_approval_ttl_default_is_operator_reviewable() -> None:
    assert DEFAULT_PROFILE_SEED_APPROVAL_TTL_MINUTES == 120
    assert (
        MIN_PROFILE_SEED_APPROVAL_TTL_MINUTES
        <= DEFAULT_PROFILE_SEED_APPROVAL_TTL_MINUTES
        <= MAX_PROFILE_SEED_APPROVAL_TTL_MINUTES
    )


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


def test_profile_seed_cli_rejects_too_short_approval_ttl() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/seed_memory_profile_proposals.py",
            "--nodes-only",
            "--approval-ttl-minutes",
            "9",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--approval-ttl-minutes must be between" in result.stderr


def test_profile_semantic_projection_builds_editable_facts() -> None:
    graph_payload = _profile_graph_payload()

    projection = build_profile_semantic_projection(
        graph_payload,
        {"semantic": []},
    )

    assert projection["candidate_count"] == len(PROFILE_NODES) - 1
    assert projection["create_count"] == len(PROFILE_NODES) - 1
    requests = projection["semantic_requests"]
    assert {request["source_action"] for request in requests} == {
        PROFILE_SEMANTIC_SOURCE_ACTION
    }
    assert "Ken Haas" not in {request["fact"] for request in requests}
    assert _request_for_slug(requests, "microsoft-managing-director-fsi")[
        "category"
    ] == "person"
    assert _request_for_slug(requests, "at0-private-ai-operating-system")[
        "category"
    ] == "project"


def test_profile_semantic_projection_skips_existing_projection() -> None:
    graph_payload = _profile_graph_payload()
    existing_slug = "microsoft-managing-director-fsi"
    semantic_payload = {
        "semantic": [
            {
                "id": "existing",
                "fact": "already saved",
                "provenance": {
                    "source_surface": "profile_seed",
                    "source_action": PROFILE_SEMANTIC_SOURCE_ACTION,
                    "source_thread_id": f"profile:{PROFILE_SEED_VERSION}:{existing_slug}",
                },
            }
        ]
    }

    projection = build_profile_semantic_projection(graph_payload, semantic_payload)

    assert projection["create_count"] == len(PROFILE_NODES) - 2
    assert all(
        not str(request["source_thread_id"]).endswith(existing_slug)
        for request in projection["semantic_requests"]
    )
    assert any(
        row["external_ref_id"] == existing_slug
        and row["reason"] == "semantic_projection_exists"
        for row in projection["skipped"]
    )


def test_profile_semantic_projection_cli_previews_offline_json(tmp_path) -> None:
    graph_path = tmp_path / "graph.json"
    semantic_path = tmp_path / "semantic.json"
    graph_path.write_text(json.dumps(_profile_graph_payload()))
    semantic_path.write_text(json.dumps({"semantic": []}))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/project_profile_graph_to_semantic.py",
            "--graph-json",
            str(graph_path),
            "--semantic-json",
            str(semantic_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "preview"
    assert payload["create_count"] == len(PROFILE_NODES) - 1


def _profile_graph_payload() -> dict[str, list[dict[str, object]]]:
    nodes: list[dict[str, object]] = []
    for index, proposal in enumerate(build_profile_node_proposals(principal_id="ken")):
        nodes.append(
            {
                **proposal["payload"],
                "id": f"11111111-1111-4111-8111-{index + 1:012d}",
                "temporal_state": "active",
                "retrieval_state": "current",
            }
        )
    return {"nodes": nodes, "edges": []}


def _request_for_slug(
    requests: list[dict[str, object]],
    slug: str,
) -> dict[str, object]:
    for request in requests:
        if str(request.get("source_thread_id") or "").endswith(slug):
            return request
    raise AssertionError(f"missing request for {slug}")
