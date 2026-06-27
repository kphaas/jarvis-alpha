#!/usr/bin/env python3
"""Authenticated live smoke for Memory temporal graph reads.

Checks:
- Bearer auth can read the current user's memory summary.
- Current user graph endpoint returns sanitized node/edge arrays.
- Admin per-user graph endpoint returns the same sanitized graph contract.
- Admin graph health and proposal metadata endpoints are reachable.
- Graph history endpoint is reachable when a node is available.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
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
    _optional_string,
    _safe_error,
    _smoke_token,
)

VALID_GRAPH_RETRIEVAL_STATES = frozenset(
    {"current", "future", "historical", "needs_refresh"}
)


@dataclass(frozen=True)
class SmokeResult:
    status: str
    detail: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("MEMORY_GRAPH_SMOKE_BASE_URL", DEFAULT_BASE_URL),
        help="Alpha Brain base URL to probe.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("MEMORY_GRAPH_SMOKE_PROFILE", DEFAULT_PROFILE),
        help="Profile passed to scripts/gen_test_token.py.",
    )
    parser.add_argument(
        "--token",
        default=(
            os.getenv("MEMORY_GRAPH_SMOKE_TOKEN")
            or os.getenv("MEMORY_CORE_SMOKE_TOKEN")
            or os.getenv("HELM_ASK_SMOKE_TOKEN")
            or os.getenv("BEACON_SMOKE_TOKEN")
        ),
        help="Optional pre-generated bearer token.",
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv("MEMORY_GRAPH_SMOKE_TOKEN_SSH_TARGET", DEFAULT_SSH_TARGET),
        help="SSH target used to generate a short-lived bearer token.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("MEMORY_GRAPH_SMOKE_TIMEOUT", "45")),
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--principal-id",
        default=os.getenv("MEMORY_GRAPH_SMOKE_PRINCIPAL", "ken"),
        help="Admin graph principal to validate without browser PIN flow.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = _smoke_token(
        explicit_token=args.token,
        profile=args.profile,
        base_url=base_url,
        token_ssh_target=args.token_ssh_target,
    )
    results = run_memory_graph_smoke(
        base_url=base_url,
        token=token,
        timeout=args.timeout,
        principal_id=args.principal_id,
    )
    failures = [name for name, result in results.items() if result.status != "passed"]
    status = "passed" if not failures else "failed"
    _emit(
        {
            "status": status,
            "checks": {name: asdict(result) for name, result in results.items()},
        }
    )
    return 0 if status == "passed" else 2


def run_memory_graph_smoke(
    *,
    base_url: str,
    token: str,
    timeout: int,
    principal_id: str = "ken",
) -> dict[str, SmokeResult]:
    results: dict[str, SmokeResult] = {}
    try:
        summary = _call_json(
            "GET",
            base_url,
            "/v1/memory/summary?semantic_limit=1&working_limit=1",
            token,
            None,
            timeout=timeout,
        )
        user_id = _optional_string(summary.get("user_id"))
        if not user_id:
            raise RuntimeError("memory summary did not return user_id")
        results["auth_summary"] = SmokeResult("passed", {"user_id": _short_id(user_id)})

        graph = _call_json(
            "GET",
            base_url,
            "/v1/memory/graph?limit=100",
            token,
            None,
            timeout=timeout,
        )
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        temporal_contract = _temporal_contract(nodes, edges)
        results["current_graph_read"] = SmokeResult(
            "passed"
            if graph.get("status") == "ok"
            and bool(temporal_contract["has_fields"])
            and bool(temporal_contract["valid_retrieval_states"])
            and _has_review_fields(nodes, edges)
            else "failed",
            {
                "node_count": len(nodes),
                "edge_count": len(edges),
                **temporal_contract,
                "review_fields": _has_review_fields(nodes, edges),
            },
        )

        admin_graph = _call_json(
            "GET",
            base_url,
            f"/v1/memory/admin/users/{principal_id}/graph?limit=100",
            token,
            None,
            timeout=timeout,
        )
        admin_nodes = (
            admin_graph.get("nodes")
            if isinstance(admin_graph.get("nodes"), list)
            else []
        )
        admin_edges = (
            admin_graph.get("edges")
            if isinstance(admin_graph.get("edges"), list)
            else []
        )
        admin_temporal_contract = _temporal_contract(admin_nodes, admin_edges)
        results["admin_user_graph_read"] = SmokeResult(
            "passed"
            if admin_graph.get("status") == "ok"
            and bool(admin_temporal_contract["has_fields"])
            and bool(admin_temporal_contract["valid_retrieval_states"])
            and _has_review_fields(admin_nodes, admin_edges)
            else "failed",
            {
                "principal_id": principal_id,
                "node_count": len(admin_nodes),
                "edge_count": len(admin_edges),
                **admin_temporal_contract,
                "review_fields": _has_review_fields(admin_nodes, admin_edges),
            },
        )

        health = _call_json(
            "GET",
            base_url,
            "/v1/memory/admin/graph/health",
            token,
            None,
            timeout=timeout,
        )
        results["admin_graph_health"] = SmokeResult(
            "passed" if health.get("status") == "ok" else "failed",
            {
                "node_count": _int_value(health.get("node_count")),
                "edge_count": _int_value(health.get("edge_count")),
                "open_proposals": _int_value(health.get("open_proposals")),
            },
        )

        proposals = _call_json(
            "GET",
            base_url,
            "/v1/memory/admin/graph/proposals?state=open&limit=5",
            token,
            None,
            timeout=timeout,
        )
        proposal_rows = (
            proposals.get("proposals")
            if isinstance(proposals.get("proposals"), list)
            else []
        )
        results["admin_graph_proposals"] = SmokeResult(
            "passed"
            if proposals.get("status") == "ok"
            and all(
                "payload" not in item
                for item in proposal_rows
                if isinstance(item, dict)
            )
            else "failed",
            {"proposal_count": len(proposal_rows), "payload_redacted": True},
        )

        node_id = _first_graph_node_id(nodes)
        if node_id:
            history = _call_json(
                "GET",
                base_url,
                f"/v1/memory/graph/history/{node_id}?limit=5",
                token,
                None,
                timeout=timeout,
            )
            events = (
                history.get("events") if isinstance(history.get("events"), list) else []
            )
            results["graph_history_read"] = SmokeResult(
                "passed" if history.get("status") == "ok" else "failed",
                {"event_count": len(events)},
            )
        else:
            results["graph_history_read"] = SmokeResult(
                "passed",
                {"skipped": True, "reason": "no_active_nodes"},
            )
    except Exception as exc:
        results.setdefault(
            "runtime",
            SmokeResult("failed", {"error": _safe_error(exc)}),
        )
    return results


def _first_graph_node_id(nodes: list[object]) -> str | None:
    for node in nodes:
        if isinstance(node, dict):
            node_id = _optional_string(node.get("id"))
            if node_id:
                return node_id
    return None


def _has_temporal_fields(nodes: list[object], edges: list[object]) -> bool:
    return bool(_temporal_contract(nodes, edges)["has_fields"])


def _temporal_contract(nodes: list[object], edges: list[object]) -> dict[str, object]:
    rows = [*nodes, *edges]
    if not rows:
        return {
            "has_fields": True,
            "valid_retrieval_states": True,
            "retrieval_states": [],
        }

    retrieval_states: list[str] = []
    has_fields = True
    valid_retrieval_states = True
    for row in rows:
        if not isinstance(row, dict):
            has_fields = False
            continue
        if "temporal_state" not in row or "retrieval_state" not in row:
            has_fields = False
            continue
        retrieval_state = str(row.get("retrieval_state") or "")
        retrieval_states.append(retrieval_state)
        if retrieval_state not in VALID_GRAPH_RETRIEVAL_STATES:
            valid_retrieval_states = False

    return {
        "has_fields": has_fields,
        "valid_retrieval_states": valid_retrieval_states,
        "retrieval_states": sorted(set(retrieval_states)),
    }


def _has_review_fields(nodes: list[object], edges: list[object]) -> bool:
    rows = [*nodes, *edges]
    if not rows:
        return True
    required = {
        "review_action",
        "review_priority",
        "review_reason",
        "review_due_at",
        "open_ended",
    }
    return all(isinstance(row, dict) and required.issubset(row) for row in rows)


def _int_value(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _short_id(value: str) -> str:
    return value[:8]


if __name__ == "__main__":
    raise SystemExit(main())
