from __future__ import annotations

import subprocess
import sys

from scripts import smoke_memory_graph


def test_memory_graph_smoke_script_runs_as_file() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/smoke_memory_graph.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Authenticated live smoke" in result.stdout


def test_memory_graph_smoke_checks_auth_graph_health_and_history(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_call_json(
        method: str,
        base_url: str,
        path: str,
        token: str,
        body: dict | None,
        *,
        timeout: int,
    ) -> dict:
        assert method == "GET"
        assert base_url == "https://alpha.example"
        assert token == "secret-token"
        assert body is None
        assert timeout == 12
        calls.append(path)
        if path.startswith("/v1/memory/summary"):
            return {"user_id": "11111111-1111-4111-8111-111111111111"}
        if path == "/v1/memory/graph?limit=100":
            return {
                "status": "ok",
                "nodes": [
                    {
                        "id": "22222222-2222-4222-8222-222222222222",
                        "temporal_state": "active",
                        "retrieval_state": "current",
                    }
                ],
                "edges": [],
            }
        if path == "/v1/memory/admin/graph/health":
            return {
                "status": "ok",
                "node_count": 1,
                "edge_count": 0,
                "open_proposals": 0,
            }
        if path == "/v1/memory/admin/graph/proposals?state=open&limit=5":
            return {"status": "ok", "proposals": [{"proposal_id": "proposal-1"}]}
        if path.startswith("/v1/memory/graph/history/"):
            return {"status": "ok", "events": [{"id": "event-1"}]}
        raise AssertionError(path)

    monkeypatch.setattr(smoke_memory_graph, "_call_json", fake_call_json)

    results = smoke_memory_graph.run_memory_graph_smoke(
        base_url="https://alpha.example",
        token="secret-token",
        timeout=12,
    )

    assert list(results) == [
        "auth_summary",
        "current_graph_read",
        "admin_graph_health",
        "admin_graph_proposals",
        "graph_history_read",
    ]
    assert all(result.status == "passed" for result in results.values())
    assert results["current_graph_read"].detail["temporal_fields"] is True
    assert calls[-1] == (
        "/v1/memory/graph/history/22222222-2222-4222-8222-222222222222?limit=5"
    )
