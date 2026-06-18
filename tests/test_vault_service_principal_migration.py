from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain/db/migrations/20260618_183000_vault_endpoint_service_principal.sql"
)


def test_endpoint_service_principal_migration_seeds_alpha_user_and_workspace():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "INSERT INTO public.alpha_users" in sql
    assert "'endpoint_service'" in sql
    assert "'endpoint_service@jarvis.local'" in sql
    assert "INSERT INTO public.alpha_workspace_users" in sql
    assert "'personal', 'endpoint_service', 'member'" in sql
