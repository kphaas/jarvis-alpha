-- Migration: 20260630_190000_alpha_agentfs_workspace
-- Purpose:   Add governed per-run workspace metadata and append-only artifact
--            metadata for the local Alpha AgentFS MVP.

ALTER TABLE public.alpha_agent_runs
    ADD COLUMN IF NOT EXISTS workspace_backend TEXT NOT NULL DEFAULT 'local',
    ADD COLUMN IF NOT EXISTS workspace_root TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS policy_labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS approval_scope TEXT,
    ADD COLUMN IF NOT EXISTS retention_class TEXT NOT NULL DEFAULT 'standard';

CREATE TABLE IF NOT EXISTS public.alpha_agent_run_artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES public.alpha_agent_runs(id) ON DELETE CASCADE,
    agent_id        TEXT NOT NULL REFERENCES public.alpha_agents(agent_id),
    relative_path   TEXT NOT NULL,
    kind            TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    size_bytes      BIGINT NOT NULL,
    sha256          TEXT,
    policy_labels   JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_agent_run_artifacts_size_check
        CHECK (size_bytes >= 0),
    CONSTRAINT alpha_agent_run_artifacts_sha256_check
        CHECK (sha256 IS NULL OR sha256 ~ '^[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_alpha_agent_run_artifacts_run_created
    ON public.alpha_agent_run_artifacts(run_id, created_at DESC);

ALTER TABLE public.alpha_agent_run_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_run_artifacts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_run_artifacts_read ON public.alpha_agent_run_artifacts;
CREATE POLICY agent_run_artifacts_read ON public.alpha_agent_run_artifacts
  FOR SELECT
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR NULLIF(current_setting('rls.user_id', true), '') IS NOT NULL
  );

DROP POLICY IF EXISTS agent_run_artifacts_admin_write ON public.alpha_agent_run_artifacts;
CREATE POLICY agent_run_artifacts_admin_write ON public.alpha_agent_run_artifacts
  FOR ALL
  USING (current_setting('rls.role', true) = 'platform_admin')
  WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_run_artifacts TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_run_artifacts TO jarvis_alpha_writer;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'alpha_agent_runs'
          AND column_name = 'workspace_root'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT alpha_agent_runs.workspace_root missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename = 'alpha_agent_run_artifacts'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT alpha_agent_run_artifacts missing';
    END IF;
END;
$$;
