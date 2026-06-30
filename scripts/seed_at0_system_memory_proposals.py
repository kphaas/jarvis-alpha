#!/usr/bin/env python3
"""Queue AT-0 system capability facts as reviewed Memory graph proposals.

Default mode prints the proposal payloads. Use --queue to create reviewed graph
proposals through the Alpha API.
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

AT0_SYSTEM_PRINCIPAL = "at0_system"
AT0_SYSTEM_SEED_VERSION = "at0_system_capabilities_v1"
AT0_SYSTEM_SOURCE_SURFACE = "at0_system_seed"
AT0_SYSTEM_SOURCE = "explicit"
VALID_FROM = "2026-06-29T00:00:00Z"
DEFAULT_AT0_SYSTEM_APPROVAL_TTL_MINUTES = 720
MIN_AT0_SYSTEM_APPROVAL_TTL_MINUTES = 10
MAX_AT0_SYSTEM_APPROVAL_TTL_MINUTES = 720


@dataclass(frozen=True, slots=True)
class CapabilityNodeSeed:
    slug: str
    label_preview: str
    summary: str
    source_basis: str = "operator_approved_at0_capability_map"


CAPABILITY_NODES: tuple[CapabilityNodeSeed, ...] = (
    CapabilityNodeSeed(
        slug="alpha",
        label_preview="Alpha",
        summary="AT-0 backend control plane, memory APIs, routes, and runtime engine.",
    ),
    CapabilityNodeSeed(
        slug="helm",
        label_preview="Helm",
        summary="AT-0 operator UI for memory, graph, approvals, Ask, and workspace surfaces.",
    ),
    CapabilityNodeSeed(
        slug="ask",
        label_preview="Ask",
        summary="Clean voice/chat surface for interacting with AT-0.",
    ),
    CapabilityNodeSeed(
        slug="memory",
        label_preview="Memory",
        summary="Semantic, working, Spark, Dream, Buddy, and temporal graph memory system.",
    ),
    CapabilityNodeSeed(
        slug="spark",
        label_preview="Spark",
        summary="Review-routed learning lane for phrases, traits, and personal facts.",
    ),
    CapabilityNodeSeed(
        slug="dream",
        label_preview="Dream",
        summary="Non-explicit memory extraction pipeline that proposes reviewed writes.",
    ),
    CapabilityNodeSeed(
        slug="buddy",
        label_preview="Buddy",
        summary="Memory event and operator-notification lane with duplicate/noise controls.",
    ),
    CapabilityNodeSeed(
        slug="forge",
        label_preview="Forge",
        summary="AT-0 readiness, CI, deploy, and reliability proof system.",
    ),
    CapabilityNodeSeed(
        slug="family",
        label_preview="Family",
        summary="Child-safe family application boundary for household and girls-view work.",
    ),
)


def build_at0_system_node_proposals(
    *,
    principal_id: str = AT0_SYSTEM_PRINCIPAL,
) -> list[dict[str, Any]]:
    return [
        {
            "principal_id": principal_id,
            "proposed_action": "create_node",
            "object_type": "node",
            "source_surface": AT0_SYSTEM_SOURCE_SURFACE,
            "reason": f"Approved AT-0 capability seed: {node.summary}",
            "payload": _node_payload(node),
        }
        for node in CAPABILITY_NODES
    ]


def _node_payload(node: CapabilityNodeSeed) -> dict[str, Any]:
    label_hash = _label_hash(node.label_preview)
    return {
        "node_type": "project",
        "label_preview": node.label_preview,
        "label_hash": label_hash,
        "external_ref_type": AT0_SYSTEM_SOURCE_SURFACE,
        "external_ref_id": node.slug,
        "source": AT0_SYSTEM_SOURCE,
        "confidence": 0.94,
        "valid_from": VALID_FROM,
        "properties": {
            "domain": "at0_system",
            "fact_kind": "capability",
            "system_principal": True,
            "capability_seed": True,
            "capability_seed_version": AT0_SYSTEM_SEED_VERSION,
            "currentness_policy": "candidate_current",
            "refresh_prompt_after_days": 180,
            "entity_resolution": {
                "entity_key": _entity_key("node", "project", label_hash),
                "entity_type": "project",
                "canonical_label_hash": label_hash,
                "method": "at0_system_seed_label_hash_v1",
            },
        },
        "provenance": {
            "source_pipeline": "at0_system_graph_seed",
            "source_candidate_id": f"at0_system:{AT0_SYSTEM_SEED_VERSION}:{node.slug}",
            "source_kind": "approved_system_seed",
            "source_basis": node.source_basis,
            "contains_raw_profile_scrape": False,
        },
    }


def _entity_key(object_type: str, entity_type: str, label_hash: str) -> str:
    encoded = (
        f"{AT0_SYSTEM_SEED_VERSION}|{object_type}|{entity_type}|{label_hash}"
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
        default=os.getenv("MEMORY_AT0_SYSTEM_SEED_BASE_URL", DEFAULT_BASE_URL),
        help="Alpha Brain base URL.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("MEMORY_AT0_SYSTEM_SEED_PROFILE", DEFAULT_PROFILE),
        help="Profile passed to scripts/gen_test_token.py when --token is absent.",
    )
    parser.add_argument(
        "--token",
        default=(
            os.getenv("MEMORY_AT0_SYSTEM_SEED_TOKEN")
            or os.getenv("MEMORY_GRAPH_SMOKE_TOKEN")
            or os.getenv("MEMORY_CORE_SMOKE_TOKEN")
            or os.getenv("HELM_ASK_SMOKE_TOKEN")
        ),
        help="Optional bearer token with memory.write/admin scope.",
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv(
            "MEMORY_AT0_SYSTEM_SEED_TOKEN_SSH_TARGET", DEFAULT_SSH_TARGET
        ),
        help="SSH target used to generate a short-lived bearer token.",
    )
    parser.add_argument(
        "--principal-id",
        default=os.getenv("MEMORY_AT0_SYSTEM_SEED_PRINCIPAL", AT0_SYSTEM_PRINCIPAL),
        help="Principal whose Memory graph receives reviewed proposals.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("MEMORY_AT0_SYSTEM_SEED_TIMEOUT", "45")),
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--approval-ttl-minutes",
        type=int,
        default=int(
            os.getenv(
                "MEMORY_AT0_SYSTEM_SEED_APPROVAL_TTL_MINUTES",
                str(DEFAULT_AT0_SYSTEM_APPROVAL_TTL_MINUTES),
            )
        ),
        help=(
            "Requested approval window for queued AT-0 system seed proposals "
            f"({MIN_AT0_SYSTEM_APPROVAL_TTL_MINUTES}-"
            f"{MAX_AT0_SYSTEM_APPROVAL_TTL_MINUTES} minutes)."
        ),
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Queue proposals through /v1/memory/graph/proposals.",
    )
    args = parser.parse_args()

    if not (
        MIN_AT0_SYSTEM_APPROVAL_TTL_MINUTES
        <= args.approval_ttl_minutes
        <= MAX_AT0_SYSTEM_APPROVAL_TTL_MINUTES
    ):
        parser.error(
            "--approval-ttl-minutes must be between "
            f"{MIN_AT0_SYSTEM_APPROVAL_TTL_MINUTES} and "
            f"{MAX_AT0_SYSTEM_APPROVAL_TTL_MINUTES}"
        )

    base_url = args.base_url.rstrip("/")
    proposals = build_at0_system_node_proposals(principal_id=args.principal_id)
    if not args.queue:
        _emit(
            {
                "status": "preview",
                "principal_id": args.principal_id,
                "node_count": len(proposals),
                "proposals": proposals,
            }
        )
        return 0

    token = _smoke_token(
        explicit_token=args.token,
        profile=args.profile,
        base_url=base_url,
        token_ssh_target=args.token_ssh_target,
    )
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
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
