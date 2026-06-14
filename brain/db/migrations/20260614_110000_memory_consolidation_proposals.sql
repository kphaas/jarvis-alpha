-- ADR-0026 PR-1: reviewed consolidation proposal infrastructure.
-- Scope: proposal + ledger schema only. No archive/promote executor.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260614110000);

CREATE TABLE IF NOT EXISTS public.alpha_memory_consolidation_proposals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL,
    candidate_id        TEXT NOT NULL,
    candidate_action    TEXT NOT NULL
                        CHECK (candidate_action IN (
                            'review_for_semantic_promotion',
                            'review_for_working_decay',
                            'merge_duplicate_semantic',
                            'review_for_procedural_memory'
                        )),
    proposed_action     TEXT NOT NULL
                        CHECK (proposed_action IN (
                            'promote_episodic_to_semantic',
                            'archive_working',
                            'merge_duplicate_semantic',
                            'review_for_procedural_memory'
                        )),
    executable          BOOLEAN NOT NULL DEFAULT false,
    status              TEXT NOT NULL DEFAULT 'pending_review'
                        CHECK (status IN (
                            'pending_review',
                            'queued',
                            'informational',
                            'approved',
                            'executed',
                            'rejected',
                            'stale',
                            'reverted'
                        )),
    approval_queue_id   UUID REFERENCES public.alpha_approval_queue(id)
                        ON DELETE RESTRICT,
    source_memory_ids   TEXT[] NOT NULL DEFAULT '{}'::text[],
    evidence            JSONB NOT NULL,
    parameters_hash     TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_memory_consolidation_proposals_hash_check
        CHECK (parameters_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT alpha_memory_consolidation_proposals_executable_check
        CHECK (
            (executable AND proposed_action IN (
                'promote_episodic_to_semantic',
                'archive_working'
            ))
            OR
            (NOT executable AND proposed_action IN (
                'merge_duplicate_semantic',
                'review_for_procedural_memory'
            ))
        ),
    CONSTRAINT alpha_memory_consolidation_proposals_executable_status_check
        CHECK (
            (executable AND status <> 'informational')
            OR
            (NOT executable AND status = 'informational')
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alpha_memory_consolidation_active_unique
    ON public.alpha_memory_consolidation_proposals(
        user_id,
        candidate_id,
        candidate_action
    )
    WHERE status IN (
        'pending_review',
        'queued',
        'informational',
        'approved'
    );
CREATE INDEX IF NOT EXISTS idx_alpha_memory_consolidation_user_status
    ON public.alpha_memory_consolidation_proposals(user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_memory_consolidation_queue
    ON public.alpha_memory_consolidation_proposals(approval_queue_id)
    WHERE approval_queue_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.alpha_memory_consolidation_execution_ledger (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id            UUID NOT NULL
                           REFERENCES public.alpha_memory_consolidation_proposals(id)
                           ON DELETE RESTRICT,
    approval_queue_id      UUID NOT NULL
                           REFERENCES public.alpha_approval_queue(id)
                           ON DELETE RESTRICT,
    operation              TEXT NOT NULL
                           CHECK (operation IN (
                               'promote_episodic_to_semantic',
                               'archive_working'
                           )),
    source_candidate_type  TEXT NOT NULL,
    source_memory_ids      TEXT[] NOT NULL DEFAULT '{}'::text[],
    destination_memory_ids TEXT[] NOT NULL DEFAULT '{}'::text[],
    evidence               JSONB NOT NULL,
    decision               JSONB NOT NULL,
    undo_path              JSONB NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'executed'
                           CHECK (status IN ('executed', 'reverted', 'failed')),
    executed_by            TEXT NOT NULL,
    executed_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reverted_at            TIMESTAMPTZ,
    CONSTRAINT alpha_memory_consolidation_ledger_one_execution
        UNIQUE (proposal_id, operation)
);

CREATE INDEX IF NOT EXISTS idx_alpha_memory_consolidation_ledger_proposal
    ON public.alpha_memory_consolidation_execution_ledger(proposal_id, status);
CREATE INDEX IF NOT EXISTS idx_alpha_memory_consolidation_ledger_executed
    ON public.alpha_memory_consolidation_execution_ledger(executed_at DESC);

ALTER TABLE public.alpha_memory_consolidation_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_consolidation_proposals FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_consolidation_execution_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_memory_consolidation_execution_ledger FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_memory_consolidation_proposals_admin
    ON public.alpha_memory_consolidation_proposals;
CREATE POLICY alpha_memory_consolidation_proposals_admin
    ON public.alpha_memory_consolidation_proposals
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

DROP POLICY IF EXISTS alpha_memory_consolidation_ledger_admin
    ON public.alpha_memory_consolidation_execution_ledger;
CREATE POLICY alpha_memory_consolidation_ledger_admin
    ON public.alpha_memory_consolidation_execution_ledger
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_memory_consolidation_proposals
            TO jarvis_alpha_app;
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_memory_consolidation_execution_ledger
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_memory_consolidation_proposals
            TO jarvis_alpha_writer;
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_memory_consolidation_execution_ledger
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_memory_consolidation_proposals IS
    'ADR-0026 reviewed Dream memory consolidation proposals. Creation is reviewed; execution is deferred to later PRs.';
COMMENT ON TABLE public.alpha_memory_consolidation_execution_ledger IS
    'ADR-0026 mandatory provenance and revert ledger for executed reviewed consolidation writes.';
COMMENT ON COLUMN public.alpha_memory_consolidation_proposals.candidate_action IS
    'Planner action from memory_consolidation.py. review_for_working_decay maps to archive_working.';
COMMENT ON COLUMN public.alpha_memory_consolidation_proposals.proposed_action IS
    'Executable operation for promotion/archive, or informational deferred action for duplicate/procedural candidates.';

DO $postcheck$
DECLARE
    v_missing INTEGER;
BEGIN
    SELECT count(*)::INTEGER
      INTO v_missing
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname IN (
           'alpha_memory_consolidation_proposals',
           'alpha_memory_consolidation_execution_ledger'
       )
       AND NOT (c.relrowsecurity AND c.relforcerowsecurity);

    IF COALESCE(v_missing, 0) <> 0 THEN
        RAISE EXCEPTION 'ADR-0026 proposal schema RLS postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
