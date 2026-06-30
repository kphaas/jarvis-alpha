#!/usr/bin/env python3
"""Project approved profile graph nodes into editable semantic memories.

The profile seed flow writes reviewed temporal graph rows first. Helm's Manage
Memory fact editor reads alpha_semantic_memory, so approved profile nodes need a
small idempotent projection pass before they show up as editable facts.

Default mode previews the semantic writes. Use --apply to save through the
existing /v1/memory/semantic API using provenance keys for duplicate detection.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seed_memory_profile_proposals import (  # noqa: E402
    PROFILE_PRINCIPAL,
    PROFILE_SEED_VERSION,
    PROFILE_SOURCE_SURFACE,
)
from scripts.smoke_memory_core import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_PROFILE,
    DEFAULT_SSH_TARGET,
    _call_json,
    _emit,
    _smoke_token,
)

PROFILE_SEMANTIC_SOURCE_ACTION = "profile_graph_projection"
DEFAULT_MAX_CREATE = 50

_PROJECT_FACT_KINDS = {
    "builder_project",
    "project",
    "project_operating_model",
    "public_profile_surface",
    "public_proof_surface",
}
_PROJECT_NODE_TYPES = {"project", "task"}
_CURRENT_RETRIEVAL_STATES = {"", "current", "recent"}
_ACTIVE_TEMPORAL_STATES = {"", "active", "current"}


def build_profile_semantic_projection(
    graph_payload: dict[str, Any],
    semantic_payload: dict[str, Any],
    *,
    profile_seed_version: str = PROFILE_SEED_VERSION,
    max_create: int = DEFAULT_MAX_CREATE,
) -> dict[str, Any]:
    """Return semantic save requests for approved profile graph nodes not saved yet."""
    existing = _existing_projection_keys(semantic_payload, profile_seed_version)
    candidates = _profile_graph_candidates(graph_payload, profile_seed_version)

    requests: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for node in candidates:
        source_thread_id = _source_thread_id(node, profile_seed_version)
        source_message_id = str(node.get("id") or "")
        if source_thread_id in existing["thread_ids"]:
            skipped.append(_skip(node, "semantic_projection_exists"))
            continue
        if source_message_id and source_message_id in existing["message_ids"]:
            skipped.append(_skip(node, "semantic_projection_exists"))
            continue
        if len(requests) >= max_create:
            skipped.append(_skip(node, "max_create_reached"))
            continue
        requests.append(_semantic_request(node, profile_seed_version))

    return {
        "status": "preview",
        "profile_seed_version": profile_seed_version,
        "candidate_count": len(candidates),
        "existing_projection_count": len(existing["thread_ids"]),
        "create_count": len(requests),
        "skipped_count": len(skipped),
        "semantic_requests": requests,
        "skipped": skipped,
    }


def _profile_graph_candidates(
    graph_payload: dict[str, Any],
    profile_seed_version: str,
) -> list[dict[str, Any]]:
    nodes = graph_payload.get("nodes") if isinstance(graph_payload, dict) else []
    candidates: list[dict[str, Any]] = []
    for row in nodes if isinstance(nodes, list) else []:
        if not isinstance(row, dict):
            continue
        properties = _as_dict(row.get("properties"))
        if properties.get("profile_seed") is not True:
            continue
        if str(properties.get("profile_seed_version") or "") != profile_seed_version:
            continue
        if str(row.get("external_ref_type") or "") != PROFILE_SOURCE_SURFACE:
            continue
        if _is_identity_node(row):
            continue
        if str(row.get("temporal_state") or "") not in _ACTIVE_TEMPORAL_STATES:
            continue
        if str(row.get("retrieval_state") or "") not in _CURRENT_RETRIEVAL_STATES:
            continue
        label = str(row.get("label_preview") or "").strip()
        if len(label) < 3:
            continue
        candidates.append(row)
    return candidates


def _existing_projection_keys(
    semantic_payload: dict[str, Any],
    profile_seed_version: str,
) -> dict[str, set[str]]:
    rows = semantic_payload.get("semantic") if isinstance(semantic_payload, dict) else []
    thread_ids: set[str] = set()
    message_ids: set[str] = set()
    prefix = f"profile:{profile_seed_version}:"
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        provenance = _as_dict(row.get("provenance"))
        thread_id = str(provenance.get("source_thread_id") or "")
        message_id = str(provenance.get("source_message_id") or "")
        if thread_id.startswith(prefix):
            thread_ids.add(thread_id)
        if (
            provenance.get("source_surface") == PROFILE_SOURCE_SURFACE
            and provenance.get("source_action") == PROFILE_SEMANTIC_SOURCE_ACTION
            and message_id
        ):
            message_ids.add(message_id)
    return {"thread_ids": thread_ids, "message_ids": message_ids}


def _semantic_request(
    node: dict[str, Any],
    profile_seed_version: str,
) -> dict[str, Any]:
    return {
        "fact": str(node.get("label_preview") or "").strip(),
        "category": _semantic_category(node),
        "source_surface": PROFILE_SOURCE_SURFACE,
        "source_thread_id": _source_thread_id(node, profile_seed_version),
        "source_message_id": str(node.get("id") or ""),
        "source_action": PROFILE_SEMANTIC_SOURCE_ACTION,
    }


def _semantic_category(node: dict[str, Any]) -> str:
    properties = _as_dict(node.get("properties"))
    fact_kind = str(properties.get("fact_kind") or "")
    node_type = str(node.get("node_type") or "")
    if node_type in _PROJECT_NODE_TYPES or fact_kind in _PROJECT_FACT_KINDS:
        return "project"
    return "person"


def _source_thread_id(node: dict[str, Any], profile_seed_version: str) -> str:
    external_ref_id = str(node.get("external_ref_id") or node.get("id") or "")
    return f"profile:{profile_seed_version}:{external_ref_id}"


def _is_identity_node(node: dict[str, Any]) -> bool:
    label = str(node.get("label_preview") or "").strip().casefold()
    external_ref_id = str(node.get("external_ref_id") or "").strip()
    return external_ref_id == "ken-haas" or (
        str(node.get("node_type") or "") == "person" and label == "ken haas"
    )


def _skip(node: dict[str, Any], reason: str) -> dict[str, str]:
    return {
        "id": str(node.get("id") or ""),
        "external_ref_id": str(node.get("external_ref_id") or ""),
        "label_preview": str(node.get("label_preview") or ""),
        "reason": reason,
    }


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return payload


def _fetch_inputs(
    *,
    base_url: str,
    principal_id: str,
    token: str,
    timeout: int,
    limit: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    graph = _call_json(
        "GET",
        base_url,
        f"/v1/memory/admin/users/{principal_id}/graph?limit={limit}",
        token,
        None,
        timeout=timeout,
    )
    semantic = _call_json(
        "GET",
        base_url,
        f"/v1/memory/admin/users/{principal_id}?semantic_limit=200",
        token,
        None,
        timeout=timeout,
    )
    return graph, semantic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("MEMORY_PROFILE_SEMANTIC_BASE_URL", DEFAULT_BASE_URL),
        help="Alpha Brain base URL.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("MEMORY_PROFILE_SEMANTIC_PROFILE", DEFAULT_PROFILE),
        help="Profile passed to scripts/gen_test_token.py when --token is absent.",
    )
    parser.add_argument(
        "--token",
        default=(
            os.getenv("MEMORY_PROFILE_SEMANTIC_TOKEN")
            or os.getenv("MEMORY_GRAPH_SMOKE_TOKEN")
            or os.getenv("MEMORY_CORE_SMOKE_TOKEN")
            or os.getenv("HELM_ASK_SMOKE_TOKEN")
        ),
        help="Optional bearer token with memory.write/admin scope.",
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv("MEMORY_PROFILE_SEMANTIC_TOKEN_SSH_TARGET", DEFAULT_SSH_TARGET),
        help="SSH target used to generate a short-lived bearer token.",
    )
    parser.add_argument(
        "--principal-id",
        default=os.getenv("MEMORY_PROFILE_SEMANTIC_PRINCIPAL", PROFILE_PRINCIPAL),
        help="Principal whose profile graph nodes are projected.",
    )
    parser.add_argument(
        "--profile-seed-version",
        default=os.getenv("MEMORY_PROFILE_SEMANTIC_SEED_VERSION", PROFILE_SEED_VERSION),
        help="Profile seed version to project.",
    )
    parser.add_argument(
        "--graph-json",
        help="Optional local graph response JSON for offline preview/testing.",
    )
    parser.add_argument(
        "--semantic-json",
        help="Optional local admin user detail JSON for offline preview/testing.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("MEMORY_PROFILE_SEMANTIC_GRAPH_LIMIT", "1000")),
        help="Graph read limit.",
    )
    parser.add_argument(
        "--max-create",
        type=int,
        default=int(os.getenv("MEMORY_PROFILE_SEMANTIC_MAX_CREATE", str(DEFAULT_MAX_CREATE))),
        help="Maximum semantic rows to create in one run.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("MEMORY_PROFILE_SEMANTIC_TIMEOUT", "45")),
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Save missing semantic rows through /v1/memory/semantic.",
    )
    args = parser.parse_args()

    if args.max_create < 1:
        parser.error("--max-create must be at least 1")
    if args.apply and not args.token and str(args.profile) != str(args.principal_id):
        parser.error("--profile must match --principal-id unless --token is supplied")

    base_url = args.base_url.rstrip("/")
    token: str | None = None
    graph = _load_json(args.graph_json)
    semantic = _load_json(args.semantic_json)
    if graph is None or semantic is None or args.apply:
        token = _smoke_token(
            explicit_token=args.token,
            profile=args.profile,
            base_url=base_url,
            token_ssh_target=args.token_ssh_target,
        )
    if graph is None or semantic is None:
        assert token is not None
        graph, semantic = _fetch_inputs(
            base_url=base_url,
            principal_id=args.principal_id,
            token=token,
            timeout=args.timeout,
            limit=args.limit,
        )
    assert graph is not None
    assert semantic is not None

    projection = build_profile_semantic_projection(
        graph,
        semantic,
        profile_seed_version=args.profile_seed_version,
        max_create=args.max_create,
    )
    projection["principal_id"] = args.principal_id

    if not args.apply:
        _emit(projection)
        return 0

    assert token is not None
    saved: list[dict[str, Any]] = []
    for request in projection["semantic_requests"]:
        result = _call_json(
            "POST",
            base_url,
            "/v1/memory/semantic",
            token,
            request,
            timeout=args.timeout,
        )
        saved.append(
            {
                "status": result.get("status"),
                "category": request.get("category"),
                "source_thread_id": request.get("source_thread_id"),
                "memory_id": result.get("result", {}).get("id"),
            }
        )

    projection["status"] = "applied"
    projection["saved_count"] = sum(1 for row in saved if row.get("status") == "saved")
    projection["saved"] = saved
    projection.pop("semantic_requests", None)
    _emit(projection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
