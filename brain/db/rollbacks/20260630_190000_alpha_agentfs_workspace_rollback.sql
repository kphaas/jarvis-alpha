-- Rollback: 20260630_190000_alpha_agentfs_workspace

DROP TABLE IF EXISTS public.alpha_agent_run_artifacts;

ALTER TABLE public.alpha_agent_runs
    DROP COLUMN IF EXISTS retention_class,
    DROP COLUMN IF EXISTS approval_scope,
    DROP COLUMN IF EXISTS policy_labels,
    DROP COLUMN IF EXISTS workspace_root,
    DROP COLUMN IF EXISTS workspace_backend;
