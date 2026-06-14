from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260614_120000_memory_consolidation_archive_revert.sql"
)
ROLLBACK = (
    REPO_ROOT
    / "brain"
    / "db"
    / "rollbacks"
    / "20260614_120000_memory_consolidation_archive_revert_rollback.sql"
)


def test_archive_executor_is_t5_token_bound_and_not_security_write() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE OR REPLACE FUNCTION public.execute_memory_consolidation_archive"
        in source
    )
    assert "SECURITY DEFINER" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "v_proposal.approval_queue_id IS DISTINCT FROM p_approval_queue_id" in source
    assert "v_approval.status <> 'approved'" in source
    assert "v_approval.parameters_hash <> v_proposal.parameters_hash" in source
    assert "v_approval.risk_tier <> 'T5'" in source
    assert (
        "'memory_consolidation_reviewed_write' = ANY(v_approval.action_class)" in source
    )
    assert "security_write" not in source


def test_archive_executor_revalidates_candidate_and_writes_ledger_atomically() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "FOR UPDATE" in source
    assert "v_source.user_id <> v_proposal.user_id::text" in source
    assert "v_source.tier <> 'working'" in source
    assert "v_source.persistent IS DISTINCT FROM false" in source
    assert "v_source.archived_at IS NOT NULL" in source
    assert "v_source.created_at IS NULL" in source
    assert "v_source.created_at >= NOW() - INTERVAL '20 hours'" in source
    assert "INSERT INTO public.alpha_memory_consolidation_execution_ledger" in source
    assert "jsonb_build_object(\n                'id', v_source.id" in source
    assert "to_jsonb(v_source)" not in source


def test_archive_executor_is_idempotent_and_revert_is_terminal() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "v_proposal.status = 'executed'" in source
    assert "CONSOLIDATION_PROPOSAL_ALREADY_EXECUTED" in source
    assert "v_proposal.status IN ('reverted', 'rejected', 'stale')" in source
    assert "CONSOLIDATION_PROPOSAL_TERMINAL" in source
    assert "UPDATE public.alpha_approval_queue" in source
    assert "SET status = 'executed'" in source
    assert "CREATE OR REPLACE FUNCTION public.revert_consolidation" in source
    assert "v_ledger.status = 'reverted'" in source
    assert "status', 'already_reverted'" in source
    assert "CONSOLIDATION_REVERT_RESTORE_FAILED" in source


def test_buddy_hold_prevents_hard_eviction_until_terminal_decision() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "consolidation_hold BOOLEAN NOT NULL DEFAULT false" in source
    assert "mark_memory_consolidation_archive_hold" in source
    assert "COALESCE(m.consolidation_hold, false)" in source
    assert "p.status IN ('pending_review', 'queued', 'approved')" in source
    assert "CREATE OR REPLACE FUNCTION public.evict_expired_working_memory" in source
    assert "CREATE OR REPLACE FUNCTION public.get_buddy_promotion_candidates" in source


def test_child_boundary_failure_auto_reverts_and_alerts() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "v_postcheck_failed" in source
    assert "PERFORM public.revert_consolidation(p_proposal_id)" in source
    assert "Memory consolidation child boundary post-check failed" in source
    assert "'status', 'postcheck_failed_reverted'" in source


def test_archive_rollback_fails_safely_when_metadata_or_ledger_is_in_use() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert (
        "Refusing rollback: alpha_conversation_memory archive/hold metadata is in use"
        in source
    )
    assert "Refusing rollback: archive_working ledger rows exist" in source
    assert (
        "DROP FUNCTION IF EXISTS public.execute_memory_consolidation_archive" in source
    )
    assert "DROP FUNCTION IF EXISTS public.revert_consolidation" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "DROP COLUMN IF EXISTS archived_by_proposal_id" in source
    assert "DROP COLUMN IF EXISTS consolidation_hold" in source
