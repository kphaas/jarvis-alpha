from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260622_100000_temporal_graph_memory.sql"
)
ROLLBACK = (
    REPO_ROOT
    / "brain"
    / "db"
    / "rollbacks"
    / "20260622_100000_temporal_graph_memory_rollback.sql"
)


def test_temporal_graph_schema_is_force_rls_and_audited() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.alpha_memory_graph_nodes" in source
    assert "CREATE TABLE IF NOT EXISTS public.alpha_memory_graph_edges" in source
    assert "CREATE TABLE IF NOT EXISTS public.alpha_memory_graph_proposals" in source
    assert "CREATE TABLE IF NOT EXISTS public.alpha_memory_graph_audit" in source
    assert (
        "ALTER TABLE public.alpha_memory_graph_nodes FORCE ROW LEVEL SECURITY" in source
    )
    assert (
        "ALTER TABLE public.alpha_memory_graph_edges FORCE ROW LEVEL SECURITY" in source
    )
    assert (
        "ALTER TABLE public.alpha_memory_graph_proposals FORCE ROW LEVEL SECURITY"
        in source
    )
    assert (
        "ALTER TABLE public.alpha_memory_graph_audit FORCE ROW LEVEL SECURITY" in source
    )
    assert "idx_alpha_memory_graph_nodes_current" in source
    assert "idx_alpha_memory_graph_edges_current" in source


def test_temporal_graph_writes_are_proposal_bound_and_approval_gated() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.propose_memory_graph_write" in source
    assert "CREATE OR REPLACE FUNCTION public.execute_memory_graph_proposal" in source
    assert "public.enqueue_approval_request" in source
    assert "'memory_graph_reviewed_write'" in source
    assert "v_approval.risk_tier <> 'T5'" in source
    assert "v_approval.parameters_hash <> v_proposal.parameters_hash" in source
    assert "public.consume_approved_queue_item" in source
    assert "INSERT INTO public.alpha_memory_graph_audit" in source


def test_temporal_graph_reads_are_bounded_and_content_safe() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.list_memory_graph_current" in source
    assert "CREATE OR REPLACE FUNCTION public.list_memory_graph_history" in source
    assert "CREATE OR REPLACE FUNCTION public.memory_graph_health" in source
    assert "LEAST(GREATEST(COALESCE(p_limit, 100), 1), 500)" in source
    assert "review_status = 'active'" in source
    assert "valid_from <= v_as_of" in source
    assert "valid_to IS NULL OR" in source


def test_temporal_graph_public_execute_is_revoked() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "REVOKE ALL ON FUNCTION public.propose_memory_graph_write" in source
    assert "REVOKE ALL ON FUNCTION public.execute_memory_graph_proposal" in source
    assert "REVOKE ALL ON FUNCTION public.list_memory_graph_current" in source
    assert "Temporal graph memory public EXECUTE postcheck failed" in source


def test_temporal_graph_rollback_refuses_to_drop_operational_data() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert "Refusing rollback: alpha_memory_graph_audit contains rows" in source
    assert "Refusing rollback: alpha_memory_graph_proposals contains rows" in source
    assert "Refusing rollback: alpha_memory_graph_edges contains rows" in source
    assert "Refusing rollback: alpha_memory_graph_nodes contains rows" in source
    assert "DROP FUNCTION IF EXISTS public.execute_memory_graph_proposal" in source
    assert "DROP TABLE IF EXISTS public.alpha_memory_graph_nodes" in source
