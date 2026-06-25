from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import NAMESPACE_DNS, UUID, uuid5

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from brain.routes import memory_graph


NODE_ID = "11111111-1111-4111-8111-111111111111"
EDGE_ID = "22222222-2222-4222-8222-222222222222"
PROPOSAL_ID = UUID("33333333-3333-4333-8333-333333333333")
APPROVAL_ID = UUID("44444444-4444-4444-8444-444444444444")


def _request(*, scopes: list[str] | None = None, role: str = "user"):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_id="ken",
            user_sub="ken",
            role=role,
            actor_type="user",
            scopes=scopes or [],
        ),
        url=SimpleNamespace(path="/v1/memory/graph"),
    )


class FakeGraphConn:
    def __init__(self) -> None:
        self.fetchval_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchval(self, query: str, *args: object) -> dict:
        self.fetchval_calls.append((query, args))
        if "list_memory_graph_current" in query:
            return {
                "principal_id": str(args[0]),
                "as_of": "2026-06-22T00:00:00+00:00",
                "nodes": [
                    {
                        "id": NODE_ID,
                        "node_type": "project",
                        "label_hash": "a" * 64,
                        "label_preview": "Temporal graph",
                        "properties": {"status": "active"},
                        "source": "operator",
                        "confidence": 0.9,
                    }
                ],
                "edges": [
                    {
                        "id": EDGE_ID,
                        "from_node_id": NODE_ID,
                        "to_node_id": "55555555-5555-4555-8555-555555555555",
                        "edge_type": "related_to",
                        "properties": {},
                        "source": "operator",
                        "confidence": 0.8,
                    }
                ],
            }
        if "list_memory_graph_history" in query:
            return {
                "principal_id": str(args[0]),
                "object_id": str(args[1]),
                "events": [
                    {
                        "id": "66666666-6666-4666-8666-666666666666",
                        "object_type": "node",
                        "operation": "create_node",
                        "actor": "ken",
                        "source_surface": "helm",
                    }
                ],
            }
        if "memory_graph_health" in query:
            return {
                "node_count": 1,
                "edge_count": 1,
                "active_node_count": 1,
                "active_edge_count": 1,
                "open_proposals": 0,
                "stale_proposals": 0,
                "audit_rows": 1,
            }
        if "list_memory_graph_proposals" in query:
            return {
                "state": str(args[1]),
                "proposals": [
                    {
                        "proposal_id": str(PROPOSAL_ID),
                        "principal_id": str(args[0]),
                        "proposed_action": "create_node",
                        "object_type": "node",
                        "status": "queued",
                        "approval_queue_id": str(APPROVAL_ID),
                        "parameters_hash": "b" * 64,
                        "source_surface": "helm",
                        "created_by": "ken",
                    }
                ],
            }
        if "propose_memory_graph_write" in query:
            return {
                "status": "queued",
                "proposal_id": str(PROPOSAL_ID),
                "approval_queue_id": str(APPROVAL_ID),
                "parameters_hash": "b" * 64,
            }
        if "execute_memory_graph_proposal" in query:
            return {
                "status": "executed",
                "proposal_id": str(PROPOSAL_ID),
                "object_type": "node",
                "object_id": NODE_ID,
                "operation": "create_node",
            }
        raise AssertionError(f"unexpected query: {query}")


class FakeGraphError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class FakeGraphErrorConn(FakeGraphConn):
    async def fetchval(self, query: str, *args: object) -> dict:
        self.fetchval_calls.append((query, args))
        if "execute_memory_graph_proposal" in query:
            raise FakeGraphError("23514")
        raise AssertionError(f"unexpected query: {query}")


@asynccontextmanager
async def fake_rls_connection(_request: object):
    yield FakeGraphConn()


@asynccontextmanager
async def fake_platform_admin_connection(*, source: str, audit_actor: str):
    assert source == "http"
    assert audit_actor == "ken"
    yield FakeGraphConn()


@pytest.mark.asyncio
async def test_memory_graph_current_reads_current_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeGraphConn()

    @asynccontextmanager
    async def context(_request: object):
        yield conn

    monkeypatch.setattr(memory_graph, "rls_connection", context)

    response = await memory_graph.get_memory_graph(request=_request())

    assert response.status == "ok"
    assert response.principal_id == str(uuid5(NAMESPACE_DNS, "ken"))
    assert response.nodes[0].label_preview == "Temporal graph"
    assert response.nodes[0].temporal_state == "active"
    assert response.nodes[0].retrieval_state == "current"
    assert response.nodes[0].conflict_key == f"node:project:{'a' * 64}"
    assert response.edges[0].edge_type == "related_to"
    assert response.edges[0].temporal_state == "active"
    assert response.edges[0].retrieval_state == "current"
    assert response.edges[0].conflict_key == (
        f"edge:{NODE_ID}:55555555-5555-4555-8555-555555555555:related_to"
    )
    assert "list_memory_graph_current" in conn.fetchval_calls[0][0]


@pytest.mark.asyncio
async def test_admin_memory_graph_health_requires_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        memory_graph,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )

    with pytest.raises(HTTPException) as exc:
        await memory_graph.get_memory_graph_health(request=_request())

    assert exc.value.status_code == 403

    response = await memory_graph.get_memory_graph_health(
        request=_request(scopes=["memory.read"]),
    )

    assert response.node_count == 1
    assert response.audit_rows == 1


@pytest.mark.asyncio
async def test_admin_memory_graph_proposals_are_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        memory_graph,
        "platform_admin_connection",
        fake_platform_admin_connection,
    )

    response = await memory_graph.list_memory_graph_proposals(
        request=_request(scopes=["memory.read"]),
        principal_id="ken",
        state="open",
        limit=50,
    )

    assert response.proposals[0].proposal_id == str(PROPOSAL_ID)
    assert response.proposals[0].approval_queue_id == str(APPROVAL_ID)
    assert not hasattr(response.proposals[0], "payload")


@pytest.mark.asyncio
async def test_memory_graph_propose_requires_write_scope_and_queues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeGraphConn()

    @asynccontextmanager
    async def context(_request: object):
        yield conn

    monkeypatch.setattr(memory_graph, "rls_connection", context)
    body = memory_graph.MemoryGraphProposalRequest(
        proposed_action="create_node",
        object_type="node",
        payload={"node_type": "project", "label_preview": "Temporal graph"},
    )

    with pytest.raises(HTTPException) as exc:
        await memory_graph.propose_memory_graph_write(body=body, request=_request())

    assert exc.value.status_code == 403

    response = await memory_graph.propose_memory_graph_write(
        body=body,
        request=_request(scopes=["memory.write"]),
    )

    assert response.status == "queued"
    assert response.result["proposal_id"] == str(PROPOSAL_ID)
    assert "propose_memory_graph_write" in conn.fetchval_calls[0][0]


def test_memory_graph_proposal_rejects_invalid_node_payloads() -> None:
    with pytest.raises(ValidationError) as exc:
        memory_graph.MemoryGraphProposalRequest(
            proposed_action="create_node",
            object_type="node",
            payload={
                "node_type": "e2e_canary",
                "label_preview": "Disposable canary",
                "source": "helm_e2e",
            },
        )

    message = str(exc.value)
    assert "payload.node_type must be one of" in message


def test_memory_graph_proposal_rejects_invalid_archive_target() -> None:
    with pytest.raises(ValidationError) as exc:
        memory_graph.MemoryGraphProposalRequest(
            proposed_action="archive_node",
            object_type="node",
            payload={"target_id": "not-a-uuid"},
        )

    assert "payload.target_id must be a UUID" in str(exc.value)


@pytest.mark.asyncio
async def test_memory_graph_execute_requires_approval_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeGraphConn()

    @asynccontextmanager
    async def context(_request: object):
        yield conn

    monkeypatch.setattr(memory_graph, "rls_connection", context)

    with pytest.raises(HTTPException) as exc:
        await memory_graph.execute_memory_graph_proposal(
            proposal_id=PROPOSAL_ID,
            request=_request(scopes=["memory.write"]),
            x_approval_token="not-a-uuid",
        )

    assert exc.value.status_code == 400

    response = await memory_graph.execute_memory_graph_proposal(
        proposal_id=PROPOSAL_ID,
        request=_request(scopes=["memory.write"]),
        x_approval_token=str(APPROVAL_ID),
    )

    assert response.status == "executed"
    assert response.result["object_id"] == NODE_ID
    assert "execute_memory_graph_proposal" in conn.fetchval_calls[0][0]


@pytest.mark.asyncio
async def test_memory_graph_execute_sanitizes_db_constraint_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeGraphErrorConn()

    @asynccontextmanager
    async def context(_request: object):
        yield conn

    monkeypatch.setattr(memory_graph, "rls_connection", context)
    monkeypatch.setattr(memory_graph, "PostgresError", FakeGraphError)

    with pytest.raises(HTTPException) as exc:
        await memory_graph.execute_memory_graph_proposal(
            proposal_id=PROPOSAL_ID,
            request=_request(scopes=["memory.write"]),
            x_approval_token=str(APPROVAL_ID),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "memory graph payload violates schema constraints"
