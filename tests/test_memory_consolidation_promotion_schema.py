from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260614_130000_memory_consolidation_promote_demote.sql"
)
ROLLBACK = (
    REPO_ROOT
    / "brain"
    / "db"
    / "rollbacks"
    / "20260614_130000_memory_consolidation_promote_demote_rollback.sql"
)
ROUTE = REPO_ROOT / "brain" / "routes" / "memory_consolidation.py"


def test_execute_route_uses_reviewed_write_dispatcher() -> None:
    source = ROUTE.read_text(encoding="utf-8")

    assert "execute_memory_consolidation_proposal" in source
    assert "execute_memory_consolidation_archive(" not in source


def test_promotion_executor_is_t5_token_bound_and_not_security_write() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE OR REPLACE FUNCTION public.execute_memory_consolidation_promotion"
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


def test_promotion_executor_revalidates_source_and_prevents_double_promotion() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "v_source.user_id <> v_proposal.user_id::text" in source
    assert "v_source.tier NOT IN ('working', 'episodic')" in source
    assert "v_source.archived_at IS NOT NULL" in source
    assert "COALESCE(v_source.importance_score, 0) >= 0.7" in source
    assert "COALESCE(v_source.access_count, 0) >= 3" in source
    assert "ledger.operation = 'promote_episodic_to_semantic'" in source
    assert "ledger.source_memory_ids @> ARRAY[v_source_id::text]" in source
    assert "CONSOLIDATION_PROPOSAL_ALREADY_EXECUTED" in source
    assert "CONSOLIDATION_PROPOSAL_TERMINAL" in source


def test_promotion_executor_writes_dream_consolidated_fact_and_mandatory_ledger() -> (
    None
):
    source = MIGRATION.read_text(encoding="utf-8")

    assert "INSERT INTO public.alpha_semantic_memory" in source
    assert "'dream_consolidated'" in source
    assert "INSERT INTO public.alpha_memory_consolidation_execution_ledger" in source
    assert "'operation', 'delete_semantic_memory'" in source
    assert "'semantic_memory_id', v_semantic_id" in source
    assert "v_approval.expires_at IS NULL" in source
    assert "v_approval.expires_at <= NOW()" in source


def test_revert_consolidation_demotes_promoted_semantic_memory() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "v_ledger.operation = 'promote_episodic_to_semantic'" in source
    assert "DELETE FROM public.alpha_semantic_memory" in source
    assert "v_ledger.destination_memory_ids[1]::uuid" in source
    assert "CONSOLIDATION_REVERT_DEMOTE_FAILED" in source
    assert "SET status = 'reverted'" in source


def test_dispatcher_supports_archive_and_promotion_only() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE OR REPLACE FUNCTION public.execute_memory_consolidation_proposal"
        in source
    )
    assert "v_action = 'archive_working'" in source
    assert "public.execute_memory_consolidation_archive" in source
    assert "v_action = 'promote_episodic_to_semantic'" in source
    assert "public.execute_memory_consolidation_promotion" in source
    assert "CONSOLIDATION_PROPOSAL_UNSUPPORTED_ACTION" in source


def test_promotion_postcheck_auto_reverts_and_alerts() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "v_postcheck_failed" in source
    assert "PERFORM public.revert_consolidation(p_proposal_id)" in source
    assert "Memory consolidation child boundary post-check failed" in source
    assert "'status', 'postcheck_failed_reverted'" in source


def test_promotion_rollback_fails_safely_when_promotions_are_in_use() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert "Refusing rollback: promote_episodic_to_semantic ledger rows exist" in source
    assert "Refusing rollback: dream_consolidated semantic rows exist" in source
    assert (
        "DROP FUNCTION IF EXISTS public.execute_memory_consolidation_proposal" in source
    )
    assert (
        "DROP FUNCTION IF EXISTS public.execute_memory_consolidation_promotion"
        in source
    )
    assert "CREATE OR REPLACE FUNCTION public.revert_consolidation" in source
    assert "AND operation = 'archive_working'" in source
