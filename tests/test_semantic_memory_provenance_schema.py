from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260618_120000_semantic_memory_provenance_review.sql"
)
ROLLBACK = (
    REPO_ROOT
    / "brain"
    / "db"
    / "rollbacks"
    / "20260618_120000_semantic_memory_provenance_review_rollback.sql"
)


def test_semantic_memory_migration_adds_provenance_and_review_state() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS provenance JSONB" in source
    assert "ADD COLUMN IF NOT EXISTS review_status TEXT" in source
    assert "alpha_semantic_memory_review_status_check" in source
    assert "'active', 'pending_review', 'rejected', 'archived'" in source
    assert "idx_asm_user_review_status" in source


def test_semantic_memory_writer_preserves_legacy_signature() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE OR REPLACE FUNCTION public.save_semantic_memory_with_provenance"
        in source
    )
    assert "CREATE OR REPLACE FUNCTION public.save_semantic_memory(" in source
    assert "public.save_semantic_memory_with_provenance(" in source
    assert "source_surface', 'legacy_function'" in source


def test_sensitive_categories_enter_review_lane_without_raw_buddy_payload() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "WHEN p_category IN ('health', 'child_profile') THEN 'pending_review'" in source
    )
    assert "'semantic_memory_review'" in source
    assert "'contains_fact', false" in source
    assert "'memory_id', v_memory_id::text" in source


def test_review_function_and_rollback_are_safe() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.review_semantic_memory" in source
    assert "WHEN 'approve' THEN 'active'" in source
    assert "WHEN 'reject' THEN 'rejected'" in source
    assert "WHEN 'archive' THEN 'archived'" in source
    assert "Refusing rollback: semantic memory review state is in use" in rollback
    assert "Refusing rollback: semantic memory provenance is in use" in rollback
