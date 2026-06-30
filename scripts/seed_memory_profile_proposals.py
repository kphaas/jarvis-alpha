#!/usr/bin/env python3
"""Queue approved public profile facts as reviewed Memory graph proposals.

Default mode prints the proposal payloads. Use --queue to create T5-reviewed
graph proposals through the Alpha API. Edge proposals are queued only after the
endpoint nodes already exist in the active graph.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.smoke_memory_core import (
    DEFAULT_BASE_URL,
    DEFAULT_PROFILE,
    DEFAULT_SSH_TARGET,
    _call_json,
    _emit,
    _smoke_token,
)

PROFILE_SEED_VERSION = "ken_profile_v2"
PROFILE_SOURCE_SURFACE = "profile_seed"
PROFILE_SOURCE = "explicit"
PROFILE_PRINCIPAL = "ken"
VALID_FROM = "2026-06-28T00:00:00Z"
DEFAULT_PROFILE_SEED_APPROVAL_TTL_MINUTES = 120
MIN_PROFILE_SEED_APPROVAL_TTL_MINUTES = 10
MAX_PROFILE_SEED_APPROVAL_TTL_MINUTES = 720


@dataclass(frozen=True, slots=True)
class ProfileNodeSeed:
    slug: str
    node_type: str
    label_preview: str
    fact_kind: str
    summary: str
    source_basis: str = "user_approved_profile_context"


@dataclass(frozen=True, slots=True)
class ProfileEdgeSeed:
    from_slug: str
    to_slug: str
    edge_type: str
    fact_kind: str
    summary: str
    source_basis: str = "user_approved_profile_context"


PROFILE_NODES: tuple[ProfileNodeSeed, ...] = (
    ProfileNodeSeed(
        slug="ken-haas",
        node_type="person",
        label_preview="Ken Haas",
        fact_kind="person",
        summary="Public career profile subject.",
    ),
    ProfileNodeSeed(
        slug="ai-business-transformation-executive",
        node_type="fact",
        label_preview="Ken is an AI and business transformation executive.",
        fact_kind="career_positioning",
        summary="Executive positioning for career/profile recall.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="microsoft-managing-director-fsi",
        node_type="organization",
        label_preview=(
            "Ken is Managing Director of Customer Success for Microsoft's "
            "financial services customers."
        ),
        fact_kind="current_role",
        summary="Current public career role.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="financial-services-transformation",
        node_type="fact",
        label_preview=(
            "Ken leads enterprise AI, cloud, security, and data transformation "
            "for financial-services customers."
        ),
        fact_kind="industry_domain",
        summary="Financial-services transformation domain.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="azure-consumption-growth",
        node_type="fact",
        label_preview=(
            "Ken's Microsoft teams grew Azure consumption from about $1.8M "
            "to $14M+ per month."
        ),
        fact_kind="career_outcome",
        summary="Public measurable outcome from Microsoft customer-success work.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="partner-led-adoption-revenue",
        node_type="fact",
        label_preview=(
            "Ken built a partner-led adoption model that added about $30M in revenue."
        ),
        fact_kind="career_outcome",
        summary="Public measurable outcome from partner-led adoption model.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="cloud-security-data-ai",
        node_type="fact",
        label_preview="Ken's transformation stack spans Cloud, Security, Data & AI.",
        fact_kind="domain_positioning",
        summary="Career domain positioning.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="at0-private-ai-operating-system",
        node_type="project",
        label_preview="AT0 - Private AI Operating System",
        fact_kind="project",
        summary="Public AT-0 project and proof surface.",
        source_basis="linkedin_profile_and_public_profile_sites",
    ),
    ProfileNodeSeed(
        slug="ai-governance-operating-model",
        node_type="fact",
        label_preview=(
            "Ken's AI transformation approach emphasizes governed execution, "
            "human approval, security, cost control, and measurable outcomes."
        ),
        fact_kind="operating_model",
        summary="AI governance and operating-model positioning.",
        source_basis="linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="chief-ai-officer-roles",
        node_type="fact",
        label_preview="Ken is targeting Chief AI Officer and senior IT transformation roles.",
        fact_kind="career_target",
        summary="Target role positioning for career memory.",
    ),
    ProfileNodeSeed(
        slug="public-career-sites",
        node_type="fact",
        label_preview="Ken's public career surfaces include at-0.com and ken-haas.com.",
        fact_kind="public_profile_surface",
        summary="Career profile routes used as public proof surfaces.",
        source_basis="linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="ibm-cloud-security-data-ai-leadership",
        node_type="organization",
        label_preview=(
            "Ken held IBM leadership roles across cloud, security, customer "
            "success, and Data & AI from 2007 to 2022."
        ),
        fact_kind="prior_role",
        summary="Prior IBM leadership background.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="building-future-enterprises",
        node_type="organization",
        label_preview=(
            "Ken co-founded Building Future Enterprises, a nonprofit focused "
            "on underrepresented groups in business and corporate leadership."
        ),
        fact_kind="board_and_community",
        summary="Community and board profile fact.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="besn-tv-board-advisor",
        node_type="organization",
        label_preview="Ken serves on the BESN.TV Board of Advisors.",
        fact_kind="board_and_community",
        summary="Board advisor profile fact.",
        source_basis="linkedin_profile",
    ),
    ProfileNodeSeed(
        slug="education-mba-furman-bs",
        node_type="fact",
        label_preview=(
            "Ken earned an MBA from UNC Kenan-Flagler and a Furman BS in "
            "Business Administration and Computer Science."
        ),
        fact_kind="education",
        summary="Education profile fact.",
        source_basis="resume_docx",
    ),
    ProfileNodeSeed(
        slug="security-cloud-certifications",
        node_type="fact",
        label_preview=(
            "Ken's certifications include CISSP, AWS Solutions Architect "
            "Associate, Azure Fundamentals, and Open Group architecture credentials."
        ),
        fact_kind="certifications",
        summary="Security and cloud certification profile fact.",
        source_basis="resume_docx",
    ),
)

PROFILE_EDGES: tuple[ProfileEdgeSeed, ...] = (
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="microsoft-managing-director-fsi",
        edge_type="related_to",
        fact_kind="current_role",
        summary=(
            "Ken's current public role is Microsoft Managing Director of "
            "Customer Success for FSI."
        ),
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="microsoft-managing-director-fsi",
        to_slug="financial-services-transformation",
        edge_type="related_to",
        fact_kind="role_domain",
        summary="Ken's Microsoft role focuses on financial-services transformation.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="microsoft-managing-director-fsi",
        to_slug="azure-consumption-growth",
        edge_type="related_to",
        fact_kind="role_outcome",
        summary="Ken's Microsoft role connects to Azure consumption growth.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="microsoft-managing-director-fsi",
        to_slug="partner-led-adoption-revenue",
        edge_type="related_to",
        fact_kind="role_outcome",
        summary="Ken's Microsoft role connects to partner-led revenue outcomes.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="at0-private-ai-operating-system",
        edge_type="works_on",
        fact_kind="builder_project",
        summary="Ken works on AT0 as a private AI operating system.",
        source_basis="linkedin_profile_and_public_profile_sites",
    ),
    ProfileEdgeSeed(
        from_slug="at0-private-ai-operating-system",
        to_slug="ai-governance-operating-model",
        edge_type="related_to",
        fact_kind="project_operating_model",
        summary="AT0 is public proof of Ken's governed AI operating-model work.",
        source_basis="linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="ai-business-transformation-executive",
        edge_type="related_to",
        fact_kind="career_positioning",
        summary="Ken's profile is positioned around AI and business transformation.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="cloud-security-data-ai",
        edge_type="related_to",
        fact_kind="domain_positioning",
        summary="Ken's profile connects to Cloud, Security, Data & AI.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="chief-ai-officer-roles",
        edge_type="related_to",
        fact_kind="career_target",
        summary="Ken is targeting Chief AI Officer and senior transformation roles.",
    ),
    ProfileEdgeSeed(
        from_slug="at0-private-ai-operating-system",
        to_slug="public-career-sites",
        edge_type="belongs_to",
        fact_kind="public_proof_surface",
        summary="AT0 and career sites are public proof surfaces for the profile.",
        source_basis="linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="ibm-cloud-security-data-ai-leadership",
        edge_type="related_to",
        fact_kind="prior_role",
        summary=(
            "Ken's career graph includes IBM cloud, security, and Data & AI leadership."
        ),
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="building-future-enterprises",
        edge_type="related_to",
        fact_kind="board_and_community",
        summary="Ken co-founded Building Future Enterprises.",
        source_basis="resume_docx_and_linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="besn-tv-board-advisor",
        edge_type="related_to",
        fact_kind="board_and_community",
        summary="Ken serves on the BESN.TV Board of Advisors.",
        source_basis="linkedin_profile",
    ),
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="education-mba-furman-bs",
        edge_type="related_to",
        fact_kind="education",
        summary="Ken's career graph includes MBA and Furman education facts.",
        source_basis="resume_docx",
    ),
    ProfileEdgeSeed(
        from_slug="ken-haas",
        to_slug="security-cloud-certifications",
        edge_type="related_to",
        fact_kind="certifications",
        summary="Ken's career graph includes security and cloud certifications.",
        source_basis="resume_docx",
    ),
)


def build_profile_node_proposals(
    *,
    principal_id: str = PROFILE_PRINCIPAL,
) -> list[dict[str, Any]]:
    return [
        {
            "principal_id": principal_id,
            "proposed_action": "create_node",
            "object_type": "node",
            "source_surface": PROFILE_SOURCE_SURFACE,
            "reason": f"Approved profile seed: {node.summary}",
            "payload": _node_payload(node),
        }
        for node in PROFILE_NODES
    ]


def build_profile_edge_proposals(
    graph_payload: dict[str, Any],
    *,
    principal_id: str = PROFILE_PRINCIPAL,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    node_ids = _active_profile_node_ids(graph_payload)
    proposals: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for edge in PROFILE_EDGES:
        from_node_id = node_ids.get(edge.from_slug)
        to_node_id = node_ids.get(edge.to_slug)
        if not from_node_id or not to_node_id:
            skipped.append(
                {
                    "from_slug": edge.from_slug,
                    "to_slug": edge.to_slug,
                    "reason": "missing_active_endpoint_node",
                }
            )
            continue
        proposals.append(
            {
                "principal_id": principal_id,
                "proposed_action": "create_edge",
                "object_type": "edge",
                "source_surface": PROFILE_SOURCE_SURFACE,
                "reason": f"Approved profile relationship seed: {edge.summary}",
                "payload": _edge_payload(edge, from_node_id, to_node_id),
            }
        )
    return proposals, skipped


def _node_payload(node: ProfileNodeSeed) -> dict[str, Any]:
    label_hash = _label_hash(node.label_preview)
    return {
        "node_type": node.node_type,
        "label_preview": node.label_preview,
        "label_hash": label_hash,
        "external_ref_type": PROFILE_SOURCE_SURFACE,
        "external_ref_id": node.slug,
        "source": PROFILE_SOURCE,
        "confidence": 0.92,
        "valid_from": VALID_FROM,
        "properties": {
            "domain": "career",
            "fact_kind": node.fact_kind,
            "profile_seed": True,
            "profile_seed_version": PROFILE_SEED_VERSION,
            "currentness_policy": "candidate_current",
            "refresh_prompt_after_days": 180,
            "entity_resolution": {
                "entity_key": _entity_key("node", node.node_type, label_hash),
                "entity_type": node.node_type,
                "canonical_label_hash": label_hash,
                "method": "profile_seed_label_hash_v1",
            },
        },
        "provenance": {
            "source_pipeline": "profile_graph_seed",
            "source_candidate_id": f"profile:{PROFILE_SEED_VERSION}:{node.slug}",
            "source_kind": "approved_profile_seed",
            "source_basis": node.source_basis,
            "contains_raw_profile_scrape": False,
        },
    }


def _edge_payload(
    edge: ProfileEdgeSeed,
    from_node_id: str,
    to_node_id: str,
) -> dict[str, Any]:
    return {
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "edge_type": edge.edge_type,
        "source": PROFILE_SOURCE,
        "confidence": 0.9,
        "valid_from": VALID_FROM,
        "properties": {
            "domain": "career",
            "fact_kind": edge.fact_kind,
            "profile_seed": True,
            "profile_seed_version": PROFILE_SEED_VERSION,
            "currentness_policy": "candidate_current",
            "refresh_prompt_after_days": 180,
        },
        "provenance": {
            "source_pipeline": "profile_graph_seed",
            "source_candidate_id": (
                f"profile:{PROFILE_SEED_VERSION}:edge:"
                f"{edge.from_slug}:{edge.to_slug}:{edge.edge_type}"
            ),
            "source_kind": "approved_profile_seed",
            "source_basis": edge.source_basis,
            "contains_raw_profile_scrape": False,
        },
    }


def _active_profile_node_ids(graph_payload: dict[str, Any]) -> dict[str, str]:
    nodes = graph_payload.get("nodes") if isinstance(graph_payload, dict) else []
    node_ids: dict[str, str] = {}
    for row in nodes if isinstance(nodes, list) else []:
        if not isinstance(row, dict):
            continue
        if str(row.get("temporal_state") or "active") not in {"active", ""}:
            continue
        slug = ""
        if row.get("external_ref_type") == PROFILE_SOURCE_SURFACE:
            slug = str(row.get("external_ref_id") or "")
        if not slug:
            slug = _slug_by_label_hash(str(row.get("label_hash") or ""))
        if slug and row.get("id"):
            node_ids.setdefault(slug, str(row["id"]))
    return node_ids


def _slug_by_label_hash(label_hash: str) -> str:
    hashes = {_label_hash(node.label_preview): node.slug for node in PROFILE_NODES}
    return hashes.get(label_hash, "")


def _entity_key(object_type: str, entity_type: str, label_hash: str) -> str:
    encoded = (
        f"{PROFILE_SEED_VERSION}|{object_type}|{entity_type}|{label_hash}"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _label_hash(value: str) -> str:
    return hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()


def _proposal_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "proposal_id": result.get("proposal_id"),
        "approval_queue_id": result.get("approval_queue_id"),
        "parameters_hash": result.get("parameters_hash"),
        "approval_ttl_minutes": result.get("approval_ttl_minutes"),
        "approval_ttl_extended": result.get("approval_ttl_extended"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("MEMORY_PROFILE_SEED_BASE_URL", DEFAULT_BASE_URL),
        help="Alpha Brain base URL.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("MEMORY_PROFILE_SEED_PROFILE", DEFAULT_PROFILE),
        help="Profile passed to scripts/gen_test_token.py when --token is absent.",
    )
    parser.add_argument(
        "--token",
        default=(
            os.getenv("MEMORY_PROFILE_SEED_TOKEN")
            or os.getenv("MEMORY_GRAPH_SMOKE_TOKEN")
            or os.getenv("MEMORY_CORE_SMOKE_TOKEN")
            or os.getenv("HELM_ASK_SMOKE_TOKEN")
        ),
        help="Optional bearer token with memory.write/admin scope.",
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv("MEMORY_PROFILE_SEED_TOKEN_SSH_TARGET", DEFAULT_SSH_TARGET),
        help="SSH target used to generate a short-lived bearer token.",
    )
    parser.add_argument(
        "--principal-id",
        default=os.getenv("MEMORY_PROFILE_SEED_PRINCIPAL", PROFILE_PRINCIPAL),
        help="Principal whose Memory graph receives reviewed proposals.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("MEMORY_PROFILE_SEED_TIMEOUT", "45")),
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--approval-ttl-minutes",
        type=int,
        default=int(
            os.getenv(
                "MEMORY_PROFILE_SEED_APPROVAL_TTL_MINUTES",
                str(DEFAULT_PROFILE_SEED_APPROVAL_TTL_MINUTES),
            )
        ),
        help=(
            "Requested approval window for queued profile seed proposals "
            f"({MIN_PROFILE_SEED_APPROVAL_TTL_MINUTES}-"
            f"{MAX_PROFILE_SEED_APPROVAL_TTL_MINUTES} minutes)."
        ),
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Queue proposals through /v1/memory/graph/proposals.",
    )
    parser.add_argument(
        "--edges-only",
        action="store_true",
        help="Queue only relationship edges for already-approved profile nodes.",
    )
    parser.add_argument(
        "--nodes-only",
        action="store_true",
        help="Queue only profile nodes.",
    )
    args = parser.parse_args()

    if args.nodes_only and args.edges_only:
        parser.error("--nodes-only and --edges-only are mutually exclusive")
    if not (
        MIN_PROFILE_SEED_APPROVAL_TTL_MINUTES
        <= args.approval_ttl_minutes
        <= MAX_PROFILE_SEED_APPROVAL_TTL_MINUTES
    ):
        parser.error(
            "--approval-ttl-minutes must be between "
            f"{MIN_PROFILE_SEED_APPROVAL_TTL_MINUTES} and "
            f"{MAX_PROFILE_SEED_APPROVAL_TTL_MINUTES}"
        )

    base_url = args.base_url.rstrip("/")
    node_proposals = (
        []
        if args.edges_only
        else build_profile_node_proposals(principal_id=args.principal_id)
    )
    edge_proposals: list[dict[str, Any]] = []
    skipped_edges: list[dict[str, Any]] = []

    token = None
    if args.queue:
        token = _smoke_token(
            explicit_token=args.token,
            profile=args.profile,
            base_url=base_url,
            token_ssh_target=args.token_ssh_target,
        )
        if not args.nodes_only:
            graph = _call_json(
                "GET",
                base_url,
                f"/v1/memory/admin/users/{args.principal_id}/graph?limit=1000",
                token,
                None,
                timeout=args.timeout,
            )
            edge_proposals, skipped_edges = build_profile_edge_proposals(
                graph,
                principal_id=args.principal_id,
            )
    elif not args.nodes_only:
        skipped_edges = [
            {
                "from_slug": edge.from_slug,
                "to_slug": edge.to_slug,
                "reason": "preview_mode_requires_live_graph_for_endpoint_ids",
            }
            for edge in PROFILE_EDGES
        ]

    proposals = [*node_proposals, *edge_proposals]
    if not args.queue:
        _emit(
            {
                "status": "preview",
                "principal_id": args.principal_id,
                "node_count": len(node_proposals),
                "edge_count": len(edge_proposals),
                "skipped_edges": skipped_edges,
                "proposals": proposals,
            }
        )
        return 0

    assert token is not None
    queued: list[dict[str, Any]] = []
    for proposal in proposals:
        proposal_request = {
            **proposal,
            "approval_ttl_minutes": args.approval_ttl_minutes,
        }
        result = _call_json(
            "POST",
            base_url,
            "/v1/memory/graph/proposals",
            token,
            proposal_request,
            timeout=args.timeout,
        )
        queued.append(
            {
                "object_type": proposal["object_type"],
                "label_preview": proposal["payload"].get("label_preview"),
                "from_node_id": proposal["payload"].get("from_node_id"),
                "to_node_id": proposal["payload"].get("to_node_id"),
                **_proposal_summary(result.get("result", result)),
            }
        )

    _emit(
        {
            "status": "queued",
            "principal_id": args.principal_id,
            "queued_count": len(queued),
            "approval_ttl_minutes": args.approval_ttl_minutes,
            "queued": queued,
            "skipped_edges": skipped_edges,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
