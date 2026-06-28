#!/usr/bin/env python3
"""Generate deterministic Memory graph stress fixtures.

The output matches the /v1/memory/graph response shape without inserting rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, uuid5


AS_OF = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
TIERS = {
    "smoke": (25, 60),
    "dense": (250, 1_000),
    "large": (1_500, 8_000),
}
NODE_TYPES = ("person", "project", "fact", "preference", "task", "organization")
SOURCES = ("import", "spark", "dream", "operator", "explicit", "buddy")
EDGE_TYPES = ("related_to", "works_on", "belongs_to", "prefers", "depends_on", "owns")
PROJECTS = (
    "Alpha memory runtime",
    "Helm memory graph",
    "Spark learning intake",
    "Temporal recall",
    "Family planning surface",
    "Print workflow",
    "Production readiness",
    "Operator review lane",
)
PEOPLE = (
    "Synthetic operator",
    "Synthetic planning partner",
    "Synthetic reviewer",
    "Synthetic project owner",
    "Synthetic family member",
    "Synthetic service account",
)
FACTS = (
    "prefers one-page status dashboards",
    "keeps memory writes approval-gated",
    "plans trips with reviewable notes",
    "separates current facts from old facts",
    "uses Helm for operator memory management",
    "routes Spark learnings into review lanes",
    "keeps Ask clean for chat and voice",
    "requires audit evidence for production",
)


@dataclass(frozen=True)
class StressRow:
    id: str
    label: str
    node_type: str
    source: str
    cluster: str
    updated_at: str
    valid_from: str
    valid_to: str | None


def build_stress_graph(tier: str) -> dict[str, Any]:
    node_count, edge_count = TIERS[tier]
    principal_id = str(uuid5(NAMESPACE_DNS, f"memory-graph-stress:{tier}:principal"))
    rows = [_node_row(tier, index) for index in range(node_count)]
    nodes = [_node_payload(row, tier, index) for index, row in enumerate(rows)]
    edges = [_edge_payload(tier, rows, index) for index in range(edge_count)]
    return {
        "status": "ok",
        "principal_id": principal_id,
        "as_of": AS_OF.isoformat(),
        "nodes": nodes,
        "edges": edges,
    }


def _node_row(tier: str, index: int) -> StressRow:
    node_type = NODE_TYPES[index % len(NODE_TYPES)]
    source = SOURCES[index % len(SOURCES)]
    project = PROJECTS[index % len(PROJECTS)]
    person = PEOPLE[index % len(PEOPLE)]
    fact = FACTS[index % len(FACTS)]
    if node_type == "person":
        label = f"{person} {index // len(PEOPLE) + 1}"
        cluster = _slug(person)
    elif node_type == "project":
        label = project
        cluster = _slug(project)
    elif node_type == "preference":
        label = f"Operator {fact}"
        cluster = "operator-preferences"
    elif node_type == "task":
        label = f"{project} follow-up {index}"
        cluster = "review-tasks"
    elif node_type == "organization":
        label = f"{project} working group"
        cluster = _slug(project)
    else:
        label = f"{project}: {fact}"
        cluster = _slug(project)
    valid_from = AS_OF - timedelta(days=index % 120)
    valid_to = None if index % 11 else AS_OF - timedelta(days=1 + index % 30)
    updated_at = AS_OF - timedelta(hours=index % 240)
    return StressRow(
        id=str(uuid5(NAMESPACE_DNS, f"memory-graph-stress:{tier}:node:{index}")),
        label=label[:160],
        node_type=node_type,
        source=source,
        cluster=cluster,
        updated_at=updated_at.isoformat(),
        valid_from=valid_from.isoformat(),
        valid_to=valid_to.isoformat() if valid_to else None,
    )


def _node_payload(row: StressRow, tier: str, index: int) -> dict[str, Any]:
    return {
        "id": row.id,
        "node_type": row.node_type,
        "label_hash": _hash(row.label),
        "label_preview": row.label,
        "external_ref_type": "stress_fixture",
        "external_ref_id": f"{tier}:node:{index}",
        "properties": {
            "cluster": row.cluster,
            "fixture": "memory_graph_stress",
            "tier": tier,
            "synthetic": True,
            "temporal_kind": "historical" if row.valid_to else "current",
        },
        "source": row.source,
        "confidence": round(0.72 + (index % 20) / 100, 2),
        "valid_from": row.valid_from,
        "valid_to": row.valid_to,
        "created_at": row.valid_from,
        "updated_at": row.updated_at,
    }


def _edge_payload(tier: str, rows: list[StressRow], index: int) -> dict[str, Any]:
    from_index = index % len(rows)
    to_index = (index * 17 + 7) % len(rows)
    if to_index == from_index:
        to_index = (to_index + 1) % len(rows)
    edge_type = EDGE_TYPES[index % len(EDGE_TYPES)]
    valid_from = AS_OF - timedelta(days=index % 90)
    valid_to = None if index % 13 else AS_OF - timedelta(days=1 + index % 14)
    return {
        "id": str(uuid5(NAMESPACE_DNS, f"memory-graph-stress:{tier}:edge:{index}")),
        "from_node_id": rows[from_index].id,
        "to_node_id": rows[to_index].id,
        "edge_type": edge_type,
        "properties": {
            "fixture": "memory_graph_stress",
            "tier": tier,
            "synthetic": True,
            "conflict_group": f"stress:{index % 37}" if index % 19 == 0 else None,
        },
        "source": SOURCES[(index + 2) % len(SOURCES)],
        "confidence": round(0.7 + (index % 25) / 100, 2),
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat() if valid_to else None,
        "created_at": valid_from.isoformat(),
        "updated_at": (AS_OF - timedelta(minutes=index % 600)).isoformat(),
    }


def _hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    return "-".join(value.lower().replace(":", "").split())[:48]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tier", choices=sorted(TIERS), help="Fixture size to generate.")
    parser.add_argument(
        "--output", type=Path, help="Optional file path. Defaults to stdout."
    )
    args = parser.parse_args()

    payload = json.dumps(build_stress_graph(args.tier), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
