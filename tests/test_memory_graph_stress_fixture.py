from __future__ import annotations

import json
import subprocess
import sys

from scripts.seed_memory_graph_stress import TIERS, build_stress_graph


def test_memory_graph_stress_fixture_sizes_are_deterministic() -> None:
    first = build_stress_graph("dense")
    second = build_stress_graph("dense")

    assert first == second
    assert len(first["nodes"]) == TIERS["dense"][0]
    assert len(first["edges"]) == TIERS["dense"][1]


def test_memory_graph_stress_fixture_uses_api_contract_and_synthetic_labels() -> None:
    graph = build_stress_graph("smoke")

    assert graph["status"] == "ok"
    assert graph["principal_id"]
    assert graph["as_of"]
    assert {node["properties"]["fixture"] for node in graph["nodes"]} == {
        "memory_graph_stress"
    }
    assert {edge["properties"]["fixture"] for edge in graph["edges"]} == {
        "memory_graph_stress"
    }
    assert all(node["properties"]["synthetic"] is True for node in graph["nodes"])
    assert all(edge["properties"]["synthetic"] is True for edge in graph["edges"])
    assert not any(
        name in node["label_preview"].lower()
        for node in graph["nodes"]
        for name in ("ken", "sweta", "ryleigh", "sloane")
    )


def test_memory_graph_stress_fixture_cli_outputs_json() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/seed_memory_graph_stress.py", "smoke"],
        check=True,
        capture_output=True,
        text=True,
    )
    graph = json.loads(result.stdout)

    assert len(graph["nodes"]) == TIERS["smoke"][0]
    assert len(graph["edges"]) == TIERS["smoke"][1]
