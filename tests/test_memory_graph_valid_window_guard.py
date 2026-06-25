from pathlib import Path


MIGRATION = Path(
    "brain/db/migrations/20260623_153600_memory_graph_valid_window_guard.sql"
)
ROLLBACK = Path(
    "brain/db/rollbacks/20260623_153600_memory_graph_valid_window_guard_rollback.sql"
)
PUBLIC_REVOKE_MIGRATION = Path(
    "brain/db/migrations/20260623_205000_memory_graph_valid_window_public_revoke.sql"
)
PUBLIC_REVOKE_ROLLBACK = Path(
    "brain/db/rollbacks/20260623_205000_memory_graph_valid_window_public_revoke_rollback.sql"
)
READINESS_SCRIPT = Path("scripts/check_memory_production_readiness.py")


def test_memory_graph_valid_window_guard_preserves_strict_windows() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE OR REPLACE FUNCTION public.enforce_memory_graph_valid_window" in source
    )
    assert "NEW.valid_to <= NEW.valid_from" in source
    assert "NEW.valid_to := NEW.valid_from + INTERVAL '1 millisecond'" in source
    assert "alpha_memory_graph_nodes_valid_window_guard" in source
    assert "alpha_memory_graph_edges_valid_window_guard" in source
    assert "BEFORE INSERT OR UPDATE OF valid_from, valid_to" in source
    assert "memory graph valid-window guard trigger postcheck failed" in source


def test_memory_graph_valid_window_guard_rollback_is_narrow() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert (
        "DROP TRIGGER IF EXISTS alpha_memory_graph_nodes_valid_window_guard" in source
    )
    assert (
        "DROP TRIGGER IF EXISTS alpha_memory_graph_edges_valid_window_guard" in source
    )
    assert "DROP FUNCTION IF EXISTS public.enforce_memory_graph_valid_window" in source
    assert "DROP TABLE" not in source
    assert "DELETE FROM" not in source


def test_memory_graph_valid_window_helper_public_execute_is_revoked() -> None:
    source = PUBLIC_REVOKE_MIGRATION.read_text(encoding="utf-8")
    readiness = READINESS_SCRIPT.read_text(encoding="utf-8")

    assert (
        "REVOKE EXECUTE ON FUNCTION public.enforce_memory_graph_valid_window()"
        in source
    )
    assert "FROM PUBLIC" in source
    assert "aclexplode(" in source
    assert "acl.grantee = 0" in source
    assert (
        "memory graph valid-window helper public EXECUTE revoke postcheck failed"
        in source
    )
    assert "('public.enforce_memory_graph_valid_window()', false)" in readiness


def test_memory_graph_valid_window_helper_public_revoke_rollback_is_narrow() -> None:
    source = PUBLIC_REVOKE_ROLLBACK.read_text(encoding="utf-8")

    assert (
        "GRANT EXECUTE ON FUNCTION public.enforce_memory_graph_valid_window()" in source
    )
    assert "TO PUBLIC" in source
    assert "DROP FUNCTION" not in source
    assert "DROP TRIGGER" not in source
    assert "DROP TABLE" not in source
