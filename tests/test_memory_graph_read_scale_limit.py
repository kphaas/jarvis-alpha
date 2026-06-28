from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT / "brain/db/migrations/20260627_210000_memory_graph_read_scale_limit.sql"
)
ROLLBACK = (
    REPO_ROOT
    / "brain/db/rollbacks/20260627_210000_memory_graph_read_scale_limit_rollback.sql"
)
ROUTE = REPO_ROOT / "brain/routes/memory_graph.py"


def test_memory_graph_read_scale_limit_migration_is_reversible() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")

    assert "pg_get_functiondef" in migration
    assert "LEAST(GREATEST(COALESCE(p_limit, 100), 1), 1000)" in migration
    assert "LEAST(GREATEST(COALESCE(p_limit, 100), 1), 500)" in rollback
    assert "RAISE EXCEPTION" in migration
    assert "RAISE EXCEPTION" in rollback


def test_memory_graph_routes_allow_v2_scale_limit() -> None:
    source = ROUTE.read_text(encoding="utf-8")

    assert source.count("Query(default=100, ge=1, le=1000)") >= 2
