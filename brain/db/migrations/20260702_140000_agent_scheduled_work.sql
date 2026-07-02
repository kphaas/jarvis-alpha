-- Migration: 20260702_140000_agent_scheduled_work
-- Purpose:   Add governed scheduled work that materializes due schedules into
--            Agent Board work items without bypassing the approval/executor path.

CREATE TABLE IF NOT EXISTS public.alpha_agent_scheduled_work (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id            TEXT NOT NULL DEFAULT COALESCE(NULLIF(current_setting('rls.workspace_id', true), ''), 'default'),
    title                   TEXT NOT NULL,
    description             TEXT NOT NULL DEFAULT '',
    schedule_text           TEXT NOT NULL,
    schedule_kind           TEXT NOT NULL,
    day_of_week             SMALLINT,
    time_of_day             TIME NOT NULL,
    timezone                TEXT NOT NULL DEFAULT 'America/New_York',
    status                  TEXT NOT NULL DEFAULT 'active',
    source_surface          TEXT NOT NULL DEFAULT 'system',
    role                    TEXT NOT NULL DEFAULT 'general',
    priority                INTEGER NOT NULL DEFAULT 5,
    assigned_agent_id       TEXT REFERENCES public.alpha_agents(agent_id) ON DELETE SET NULL,
    required_skills         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    approval_tier           TEXT NOT NULL DEFAULT 'T1',
    next_run_at             TIMESTAMPTZ,
    last_run_at             TIMESTAMPTZ,
    last_work_item_id       UUID REFERENCES public.alpha_agent_work_items(id) ON DELETE SET NULL,
    acceptance_criteria     JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by              TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_agent_scheduled_work_title_check
        CHECK (length(btrim(title)) > 0),
    CONSTRAINT alpha_agent_scheduled_work_schedule_text_check
        CHECK (length(btrim(schedule_text)) > 0),
    CONSTRAINT alpha_agent_scheduled_work_kind_check
        CHECK (schedule_kind IN ('once', 'daily', 'weekly')),
    CONSTRAINT alpha_agent_scheduled_work_day_check
        CHECK (day_of_week IS NULL OR day_of_week BETWEEN 0 AND 6),
    CONSTRAINT alpha_agent_scheduled_work_status_check
        CHECK (status IN ('active', 'paused', 'cancelled', 'completed')),
    CONSTRAINT alpha_agent_scheduled_work_source_check
        CHECK (source_surface IN ('helm_companion', 'helm_ask', 'alpha', 'chatops', 'manual', 'system')),
    CONSTRAINT alpha_agent_scheduled_work_role_check
        CHECK (role IN ('general', 'research', 'code', 'review', 'deploy', 'monitor')),
    CONSTRAINT alpha_agent_scheduled_work_priority_check
        CHECK (priority BETWEEN 1 AND 10),
    CONSTRAINT alpha_agent_scheduled_work_tier_check
        CHECK (approval_tier IN ('T1', 'T2', 'T3', 'T4', 'T5')),
    CONSTRAINT alpha_agent_scheduled_work_acceptance_array_check
        CHECK (jsonb_typeof(acceptance_criteria) = 'array'),
    CONSTRAINT alpha_agent_scheduled_work_metadata_object_check
        CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE IF NOT EXISTS public.alpha_agent_scheduled_work_runs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduled_work_id       UUID NOT NULL REFERENCES public.alpha_agent_scheduled_work(id) ON DELETE CASCADE,
    work_item_id            UUID REFERENCES public.alpha_agent_work_items(id) ON DELETE SET NULL,
    run_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status                  TEXT NOT NULL,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_agent_scheduled_work_runs_status_check
        CHECK (status IN ('queued', 'skipped', 'failed')),
    CONSTRAINT alpha_agent_scheduled_work_runs_metadata_object_check
        CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_alpha_agent_scheduled_work_due
    ON public.alpha_agent_scheduled_work(status, next_run_at, priority DESC)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_alpha_agent_scheduled_work_workspace_status
    ON public.alpha_agent_scheduled_work(workspace_id, status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_alpha_agent_scheduled_work_runs_schedule
    ON public.alpha_agent_scheduled_work_runs(scheduled_work_id, run_at DESC);

DROP TRIGGER IF EXISTS trg_agent_scheduled_work_updated ON public.alpha_agent_scheduled_work;
CREATE TRIGGER trg_agent_scheduled_work_updated
    BEFORE UPDATE ON public.alpha_agent_scheduled_work
    FOR EACH ROW EXECUTE FUNCTION public.update_task_timestamp();

ALTER TABLE public.alpha_agent_scheduled_work ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_scheduled_work FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_scheduled_work_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_scheduled_work_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_scheduled_work_read ON public.alpha_agent_scheduled_work;
CREATE POLICY agent_scheduled_work_read ON public.alpha_agent_scheduled_work
  FOR SELECT
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR (
      current_setting('rls.role', true) = 'user'
      AND workspace_id = COALESCE(NULLIF(current_setting('rls.workspace_id', true), ''), 'default')
    )
  );

DROP POLICY IF EXISTS agent_scheduled_work_operator_write ON public.alpha_agent_scheduled_work;
CREATE POLICY agent_scheduled_work_operator_write ON public.alpha_agent_scheduled_work
  FOR ALL
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR (
      current_setting('rls.role', true) = 'user'
      AND workspace_id = COALESCE(NULLIF(current_setting('rls.workspace_id', true), ''), 'default')
    )
  )
  WITH CHECK (
    current_setting('rls.role', true) = 'platform_admin'
    OR (
      current_setting('rls.role', true) = 'user'
      AND workspace_id = COALESCE(NULLIF(current_setting('rls.workspace_id', true), ''), 'default')
    )
  );

DROP POLICY IF EXISTS agent_scheduled_work_runs_read ON public.alpha_agent_scheduled_work_runs;
CREATE POLICY agent_scheduled_work_runs_read ON public.alpha_agent_scheduled_work_runs
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
        FROM public.alpha_agent_scheduled_work sw
       WHERE sw.id = scheduled_work_id
    )
  );

DROP POLICY IF EXISTS agent_scheduled_work_runs_operator_write ON public.alpha_agent_scheduled_work_runs;
CREATE POLICY agent_scheduled_work_runs_operator_write ON public.alpha_agent_scheduled_work_runs
  FOR ALL
  USING (
    EXISTS (
      SELECT 1
        FROM public.alpha_agent_scheduled_work sw
       WHERE sw.id = scheduled_work_id
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
        FROM public.alpha_agent_scheduled_work sw
       WHERE sw.id = scheduled_work_id
    )
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_scheduled_work TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_scheduled_work TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_scheduled_work_runs TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_scheduled_work_runs TO jarvis_alpha_writer;

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('agent_schedule.read', 'agent_schedule', 'read',
     'Read governed Agent Board scheduled work definitions and run history.', 'T1', 'agents.read', 'active',
     FALSE, FALSE, FALSE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "read",
          "input_schema_ref": "registry://schemas/agent-schedule/read-v1",
          "output_schema_ref": "registry://schemas/agent-schedule/list-v1",
          "runtime": {"timeout_s": 10, "retry_policy": "none", "rate_limit": "60/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_schedule.read", "redact_fields": []},
          "compensation": "not_applicable",
          "test_ref": "tests/test_agent_schedules.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "fastapi_route",
        "operator_surface": "helm"
      }'::jsonb),
    ('agent_schedule.create', 'agent_schedule', 'create',
     'Create or update governed scheduled work that later queues Agent Board items.', 'T2', 'agents.write', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/agent-schedule/create-v1",
          "output_schema_ref": "registry://schemas/agent-schedule/item-v1",
          "runtime": {"timeout_s": 10, "retry_policy": "idempotent_retry_once", "rate_limit": "30/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_schedule.create", "redact_fields": ["body", "secret", "token"]},
          "compensation": "cancel_schedule",
          "test_ref": "tests/test_agent_schedules.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "fastapi_route",
        "operator_surface": "helm",
        "does_not_execute_agents": true
      }'::jsonb),
    ('agent_schedule.materialize_due', 'agent_schedule', 'materialize_due',
     'Materialize due scheduled work into queued Agent Board items without dispatching execution.', 'T2', 'agents.write', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/agent-schedule/materialize-due-v1",
          "output_schema_ref": "registry://schemas/agent-schedule/materialize-result-v1",
          "runtime": {"timeout_s": 20, "retry_policy": "idempotent_retry_once", "rate_limit": "12/minute/system"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_schedule.materialize_due", "redact_fields": ["body", "secret", "token"]},
          "compensation": "cancel_materialized_work_item",
          "test_ref": "tests/test_agent_schedules.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "launchagent_or_fastapi_route",
        "operator_surface": "helm",
        "does_not_execute_agents": true,
        "queues_agent_board_items": true
      }'::jsonb)
ON CONFLICT (skill_name) DO UPDATE
SET domain = EXCLUDED.domain,
    action = EXCLUDED.action,
    description = EXCLUDED.description,
    approval_tier = EXCLUDED.approval_tier,
    scope = EXCLUDED.scope,
    status = EXCLUDED.status,
    mutates_state = EXCLUDED.mutates_state,
    body_access = EXCLUDED.body_access,
    idempotency_required = EXCLUDED.idempotency_required,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_policies
         WHERE schemaname = 'public'
           AND tablename = 'alpha_agent_scheduled_work'
           AND policyname = 'agent_scheduled_work_operator_write'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT agent scheduled work RLS FAILED: write policy missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.alpha_skill_registry
         WHERE skill_name = 'agent_schedule.materialize_due'
           AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT agent scheduled work registry seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT agent scheduled work OK';
END $$;
