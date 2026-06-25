-- Migration: 20260625_130000_agent_board_work_queue
-- Purpose:   Add Alpha Agent Board work queue primitives that reference the
--            existing agent and skill registries without introducing a second
--            skill runtime.

CREATE TABLE IF NOT EXISTS public.alpha_agent_work_items (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id            TEXT NOT NULL DEFAULT COALESCE(NULLIF(current_setting('rls.workspace_id', true), ''), 'default'),
    title                   TEXT NOT NULL,
    description             TEXT NOT NULL DEFAULT '',
    source_surface          TEXT NOT NULL DEFAULT 'helm_companion',
    requested_by            TEXT NOT NULL,
    role                    TEXT NOT NULL DEFAULT 'general',
    status                  TEXT NOT NULL DEFAULT 'queued',
    priority                INTEGER NOT NULL DEFAULT 5,
    assigned_agent_id       TEXT REFERENCES public.alpha_agents(agent_id) ON DELETE SET NULL,
    required_skills         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    approval_tier           TEXT NOT NULL DEFAULT 'T1',
    approval_queue_id       UUID REFERENCES public.alpha_approval_queue(id) ON DELETE SET NULL,
    task_graph_id           UUID REFERENCES public.alpha_task_graphs(id) ON DELETE SET NULL,
    due_at                  TIMESTAMPTZ,
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    blocked_reason          TEXT,
    acceptance_criteria     JSONB NOT NULL DEFAULT '[]'::jsonb,
    handoff                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_agent_work_items_title_check
        CHECK (length(btrim(title)) > 0),
    CONSTRAINT alpha_agent_work_items_source_check
        CHECK (source_surface IN ('helm_companion', 'helm_ask', 'alpha', 'chatops', 'manual', 'system')),
    CONSTRAINT alpha_agent_work_items_role_check
        CHECK (role IN ('general', 'research', 'code', 'review', 'deploy', 'monitor')),
    CONSTRAINT alpha_agent_work_items_status_check
        CHECK (status IN ('queued', 'in_progress', 'blocked', 'needs_approval', 'handoff_ready', 'done', 'cancelled')),
    CONSTRAINT alpha_agent_work_items_priority_check
        CHECK (priority BETWEEN 1 AND 10),
    CONSTRAINT alpha_agent_work_items_tier_check
        CHECK (approval_tier IN ('T1', 'T2', 'T3', 'T4', 'T5')),
    CONSTRAINT alpha_agent_work_items_time_check
        CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at),
    CONSTRAINT alpha_agent_work_items_acceptance_array_check
        CHECK (jsonb_typeof(acceptance_criteria) = 'array'),
    CONSTRAINT alpha_agent_work_items_handoff_object_check
        CHECK (jsonb_typeof(handoff) = 'object'),
    CONSTRAINT alpha_agent_work_items_metadata_object_check
        CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE IF NOT EXISTS public.alpha_agent_work_item_events (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_item_id            UUID NOT NULL REFERENCES public.alpha_agent_work_items(id) ON DELETE CASCADE,
    event_type              TEXT NOT NULL,
    actor                   TEXT NOT NULL,
    from_status             TEXT,
    to_status               TEXT,
    message                 TEXT NOT NULL DEFAULT '',
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_agent_work_item_events_type_check
        CHECK (event_type IN ('created', 'status_changed', 'assigned', 'handoff', 'approval_linked', 'task_graph_linked', 'comment')),
    CONSTRAINT alpha_agent_work_item_events_from_status_check
        CHECK (from_status IS NULL OR from_status IN ('queued', 'in_progress', 'blocked', 'needs_approval', 'handoff_ready', 'done', 'cancelled')),
    CONSTRAINT alpha_agent_work_item_events_to_status_check
        CHECK (to_status IS NULL OR to_status IN ('queued', 'in_progress', 'blocked', 'needs_approval', 'handoff_ready', 'done', 'cancelled')),
    CONSTRAINT alpha_agent_work_item_events_metadata_object_check
        CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_alpha_agent_work_items_workspace_status
    ON public.alpha_agent_work_items(workspace_id, status, priority DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_agent_work_items_agent_status
    ON public.alpha_agent_work_items(assigned_agent_id, status);
CREATE INDEX IF NOT EXISTS idx_alpha_agent_work_items_role_status
    ON public.alpha_agent_work_items(role, status);
CREATE INDEX IF NOT EXISTS idx_alpha_agent_work_item_events_item_created
    ON public.alpha_agent_work_item_events(work_item_id, created_at DESC);

DROP TRIGGER IF EXISTS trg_agent_work_items_updated ON public.alpha_agent_work_items;
CREATE TRIGGER trg_agent_work_items_updated
    BEFORE UPDATE ON public.alpha_agent_work_items
    FOR EACH ROW EXECUTE FUNCTION public.update_task_timestamp();

ALTER TABLE public.alpha_agent_work_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_work_items FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_work_item_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_work_item_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_work_items_read ON public.alpha_agent_work_items;
CREATE POLICY agent_work_items_read ON public.alpha_agent_work_items
  FOR SELECT
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR (
      current_setting('rls.role', true) = 'user'
      AND workspace_id = COALESCE(NULLIF(current_setting('rls.workspace_id', true), ''), 'default')
    )
  );

DROP POLICY IF EXISTS agent_work_items_operator_write ON public.alpha_agent_work_items;
CREATE POLICY agent_work_items_operator_write ON public.alpha_agent_work_items
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

DROP POLICY IF EXISTS agent_work_item_events_read ON public.alpha_agent_work_item_events;
CREATE POLICY agent_work_item_events_read ON public.alpha_agent_work_item_events
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
        FROM public.alpha_agent_work_items wi
       WHERE wi.id = work_item_id
    )
  );

DROP POLICY IF EXISTS agent_work_item_events_operator_write ON public.alpha_agent_work_item_events;
CREATE POLICY agent_work_item_events_operator_write ON public.alpha_agent_work_item_events
  FOR ALL
  USING (
    EXISTS (
      SELECT 1
        FROM public.alpha_agent_work_items wi
       WHERE wi.id = work_item_id
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
        FROM public.alpha_agent_work_items wi
       WHERE wi.id = work_item_id
    )
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_work_items TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_work_items TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_work_item_events TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_work_item_events TO jarvis_alpha_writer;

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('agent_board.read', 'agent_board', 'read',
     'Read Alpha Agent Board work items, assignments, and registry summaries.', 'T1', 'agents.read', 'active',
     FALSE, FALSE, FALSE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "read",
          "input_schema_ref": "registry://schemas/agent-board/read-v1",
          "output_schema_ref": "registry://schemas/agent-board/board-v1",
          "runtime": {"timeout_s": 10, "retry_policy": "none", "rate_limit": "60/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_board.read", "redact_fields": []},
          "compensation": "not_applicable",
          "test_ref": "tests/test_agent_board.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "fastapi_route",
        "operator_surface": "helm"
      }'::jsonb),
    ('agent_board.queue_item', 'agent_board', 'queue_item',
     'Queue an operator-reviewed Alpha Agent Board work item without executing it.', 'T2', 'agents.write', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/agent-board/work-item-create-v1",
          "output_schema_ref": "registry://schemas/agent-board/work-item-v1",
          "runtime": {"timeout_s": 10, "retry_policy": "idempotent_retry_once", "rate_limit": "30/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_board.queue_item", "redact_fields": ["body", "secret", "token"]},
          "compensation": "cancel_work_item",
          "test_ref": "tests/test_agent_board.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "fastapi_route",
        "operator_surface": "helm",
        "does_not_execute_agents": true
      }'::jsonb),
    ('agent_board.update_status', 'agent_board', 'update_status',
     'Update Alpha Agent Board status and handoff metadata without bypassing approvals.', 'T2', 'agents.write', 'active',
     TRUE, FALSE, TRUE,
     '{
        "manifest": {
          "manifest_version": 1,
          "data_classification": "ops",
          "side_effect_class": "control_plane",
          "input_schema_ref": "registry://schemas/agent-board/status-update-v1",
          "output_schema_ref": "registry://schemas/agent-board/work-item-v1",
          "runtime": {"timeout_s": 10, "retry_policy": "idempotent_retry_once", "rate_limit": "60/minute/operator"},
          "cost": {"mode": "none", "max_usd_per_call": 0.0, "model_policy": null},
          "egress": {"mode": "none", "provider": null, "allowed_hosts": []},
          "audit": {"event_name": "agent_board.update_status", "redact_fields": ["body", "secret", "token"]},
          "compensation": "status_change_event_trail",
          "test_ref": "tests/test_agent_board.py",
          "runbook_ref": "docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md"
        },
        "execution_path": "fastapi_route",
        "operator_surface": "helm",
        "does_not_execute_agents": true
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
           AND tablename = 'alpha_agent_work_items'
           AND policyname = 'agent_work_items_operator_write'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT agent board RLS FAILED: write policy missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.alpha_skill_registry
         WHERE skill_name = 'agent_board.queue_item'
           AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT agent board registry seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT agent board work queue OK';
END $$;
