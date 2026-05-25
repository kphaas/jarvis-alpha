-- Migration: 20260525_180000_agent_skill_registry
-- Purpose:   Agent-management foundation. Adds durable registries for
--            callable skills and managed agents before new autonomous loops.

CREATE TABLE IF NOT EXISTS public.alpha_skill_registry (
    skill_name              TEXT PRIMARY KEY,
    domain                  TEXT NOT NULL,
    action                  TEXT NOT NULL,
    description             TEXT NOT NULL,
    approval_tier           TEXT NOT NULL,
    scope                   TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'planned',
    mutates_state           BOOLEAN NOT NULL DEFAULT FALSE,
    body_access             BOOLEAN NOT NULL DEFAULT FALSE,
    idempotency_required    BOOLEAN NOT NULL DEFAULT FALSE,
    owner                   TEXT NOT NULL DEFAULT 'ken',
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_skill_registry_name_check
        CHECK (skill_name ~ '^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$'),
    CONSTRAINT alpha_skill_registry_tier_check
        CHECK (approval_tier IN ('T1', 'T2', 'T3', 'T4', 'T5')),
    CONSTRAINT alpha_skill_registry_status_check
        CHECK (status IN ('planned', 'active', 'disabled')),
    CONSTRAINT alpha_skill_registry_domain_action_check
        CHECK (skill_name = domain || '.' || action)
);

CREATE TABLE IF NOT EXISTS public.alpha_agents (
    agent_id                TEXT PRIMARY KEY,
    display_name            TEXT NOT NULL,
    purpose                 TEXT NOT NULL,
    risk_tier               TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'planned',
    enabled                 BOOLEAN NOT NULL DEFAULT FALSE,
    owner                   TEXT NOT NULL DEFAULT 'ken',
    cadence                 TEXT,
    launch_label            TEXT,
    allowed_skills          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    allowed_scopes          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    cost_daily_cap_usd      NUMERIC(10, 4),
    model_policy            JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval_policy         JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_agents_id_check
        CHECK (agent_id ~ '^[a-z][a-z0-9_]*$'),
    CONSTRAINT alpha_agents_tier_check
        CHECK (risk_tier IN ('T1', 'T2', 'T3', 'T4', 'T5')),
    CONSTRAINT alpha_agents_status_check
        CHECK (status IN ('planned', 'active', 'disabled')),
    CONSTRAINT alpha_agents_cost_cap_check
        CHECK (cost_daily_cap_usd IS NULL OR cost_daily_cap_usd >= 0)
);

CREATE TABLE IF NOT EXISTS public.alpha_agent_runs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id                TEXT NOT NULL REFERENCES public.alpha_agents(agent_id),
    status                  TEXT NOT NULL DEFAULT 'queued',
    trigger_type            TEXT NOT NULL DEFAULT 'manual',
    trace_id                TEXT,
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    cost_usd                NUMERIC(10, 6) NOT NULL DEFAULT 0,
    error_text              TEXT,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_agent_runs_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT alpha_agent_runs_cost_check
        CHECK (cost_usd >= 0),
    CONSTRAINT alpha_agent_runs_time_check
        CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE IF NOT EXISTS public.alpha_agent_events (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id                TEXT NOT NULL REFERENCES public.alpha_agents(agent_id),
    run_id                  UUID REFERENCES public.alpha_agent_runs(id) ON DELETE SET NULL,
    event_type              TEXT NOT NULL,
    severity                TEXT NOT NULL DEFAULT 'info',
    message                 TEXT NOT NULL,
    payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_agent_events_severity_check
        CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_alpha_skill_registry_domain
    ON public.alpha_skill_registry(domain);
CREATE INDEX IF NOT EXISTS idx_alpha_skill_registry_status
    ON public.alpha_skill_registry(status);
CREATE INDEX IF NOT EXISTS idx_alpha_agents_status_enabled
    ON public.alpha_agents(status, enabled);
CREATE INDEX IF NOT EXISTS idx_alpha_agent_runs_agent_created
    ON public.alpha_agent_runs(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_agent_events_agent_created
    ON public.alpha_agent_events(agent_id, created_at DESC);

ALTER TABLE public.alpha_skill_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_skill_registry FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agents FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_agent_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS skill_registry_read ON public.alpha_skill_registry;
CREATE POLICY skill_registry_read ON public.alpha_skill_registry
  FOR SELECT
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR NULLIF(current_setting('rls.user_id', true), '') IS NOT NULL
  );

DROP POLICY IF EXISTS skill_registry_admin_write ON public.alpha_skill_registry;
CREATE POLICY skill_registry_admin_write ON public.alpha_skill_registry
  FOR ALL
  USING (current_setting('rls.role', true) = 'platform_admin')
  WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

DROP POLICY IF EXISTS agents_read ON public.alpha_agents;
CREATE POLICY agents_read ON public.alpha_agents
  FOR SELECT
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR NULLIF(current_setting('rls.user_id', true), '') IS NOT NULL
  );

DROP POLICY IF EXISTS agents_admin_write ON public.alpha_agents;
CREATE POLICY agents_admin_write ON public.alpha_agents
  FOR ALL
  USING (current_setting('rls.role', true) = 'platform_admin')
  WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

DROP POLICY IF EXISTS agent_runs_read ON public.alpha_agent_runs;
CREATE POLICY agent_runs_read ON public.alpha_agent_runs
  FOR SELECT
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR NULLIF(current_setting('rls.user_id', true), '') IS NOT NULL
  );

DROP POLICY IF EXISTS agent_runs_admin_write ON public.alpha_agent_runs;
CREATE POLICY agent_runs_admin_write ON public.alpha_agent_runs
  FOR ALL
  USING (current_setting('rls.role', true) = 'platform_admin')
  WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

DROP POLICY IF EXISTS agent_events_read ON public.alpha_agent_events;
CREATE POLICY agent_events_read ON public.alpha_agent_events
  FOR SELECT
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR NULLIF(current_setting('rls.user_id', true), '') IS NOT NULL
  );

DROP POLICY IF EXISTS agent_events_admin_write ON public.alpha_agent_events;
CREATE POLICY agent_events_admin_write ON public.alpha_agent_events
  FOR ALL
  USING (current_setting('rls.role', true) = 'platform_admin')
  WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_skill_registry TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_skill_registry TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agents TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agents TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_runs TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_runs TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_events TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_agent_events TO jarvis_alpha_writer;

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('notify.send_pushover', 'notify', 'send_pushover',
     'Send a Pushover notification to Ken.', 'T2', 'notify.send', 'planned',
     TRUE, FALSE, TRUE, '{}'::jsonb),
    ('unifi.wan_status', 'unifi', 'wan_status',
     'Read WAN status, speed, latency, and ISP state.', 'T1', 'network.read', 'active',
     FALSE, FALSE, FALSE, '{}'::jsonb),
    ('unifi.clients', 'unifi', 'clients',
     'List connected UniFi clients.', 'T1', 'network.read', 'active',
     FALSE, FALSE, FALSE, '{}'::jsonb),
    ('unifi.health_check', 'unifi', 'health_check',
     'Read controller, AP, and switch health signals.', 'T1', 'network.read', 'planned',
     FALSE, FALSE, FALSE, '{}'::jsonb),
    ('unifi.daughters_screentime', 'unifi', 'daughters_screentime',
     'Pause or resume daughters registered devices on the home network.', 'T4', 'network.screentime', 'planned',
     TRUE, FALSE, TRUE, '{"child_profile_block": false}'::jsonb),
    ('gmail.search_threads', 'gmail', 'search_threads',
     'Search Gmail threads across configured accounts.', 'T1', 'email.read', 'planned',
     FALSE, FALSE, FALSE, '{}'::jsonb),
    ('gmail.read_thread', 'gmail', 'read_thread',
     'Read Gmail thread metadata and allowed body content.', 'T1', 'email.read', 'planned',
     FALSE, TRUE, FALSE, '{}'::jsonb),
    ('gmail.draft_reply', 'gmail', 'draft_reply',
     'Create a Gmail draft without sending.', 'T2', 'email.write', 'planned',
     TRUE, FALSE, TRUE, '{}'::jsonb),
    ('gmail.send', 'gmail', 'send',
     'Send Gmail to non-VIP recipients after approval.', 'T4', 'email.send', 'planned',
     TRUE, TRUE, TRUE, '{}'::jsonb),
    ('gmail.send_vip', 'gmail', 'send_vip',
     'Send Gmail to VIP recipients under the encrypted group policy.', 'T1', 'email.send', 'planned',
     TRUE, TRUE, TRUE, '{"vip_store": "~/jarvis/.secrets/vip_groups.enc"}'::jsonb),
    ('imessage.read', 'imessage', 'read',
     'Read recent iMessage thread metadata and allowed body content.', 'T1', 'imessage.read', 'planned',
     FALSE, TRUE, FALSE, '{}'::jsonb),
    ('imessage.send', 'imessage', 'send',
     'Send iMessage to non-VIP recipients after approval.', 'T4', 'imessage.send', 'planned',
     TRUE, TRUE, TRUE, '{}'::jsonb),
    ('imessage.send_vip', 'imessage', 'send_vip',
     'Send iMessage to VIP recipients under the encrypted group policy.', 'T1', 'imessage.send', 'planned',
     TRUE, TRUE, TRUE, '{"vip_store": "~/jarvis/.secrets/vip_groups.enc"}'::jsonb),
    ('smarthome.run_trusted_scene', 'smarthome', 'run_trusted_scene',
     'Run a trusted Home Assistant scene from the approved scene list.', 'T1', 'smarthome.scene', 'planned',
     TRUE, FALSE, TRUE, '{}'::jsonb),
    ('smarthome.run_scene', 'smarthome', 'run_scene',
     'Run an unknown or not-yet-trusted Home Assistant scene after approval.', 'T4', 'smarthome.write', 'planned',
     TRUE, FALSE, TRUE, '{}'::jsonb),
    ('smarthome.set_device', 'smarthome', 'set_device',
     'Set a direct device state through Home Assistant.', 'T4', 'smarthome.write', 'planned',
     TRUE, FALSE, TRUE, '{}'::jsonb),
    ('smarthome.unlock', 'smarthome', 'unlock',
     'Unlock a physical lock through Home Assistant.', 'T5', 'smarthome.security', 'planned',
     TRUE, FALSE, TRUE, '{}'::jsonb),
    ('smarthome.alarm_disarm', 'smarthome', 'alarm_disarm',
     'Disarm a home alarm panel through Home Assistant.', 'T5', 'smarthome.security', 'planned',
     TRUE, FALSE, TRUE, '{}'::jsonb),
    ('tasks.create', 'tasks', 'create',
     'Create an Obsidian Tasks markdown checkbox.', 'T2', 'tasks.write', 'planned',
     TRUE, FALSE, TRUE, '{}'::jsonb),
    ('notes.search', 'notes', 'search',
     'Search the Obsidian vault.', 'T1', 'notes.read', 'planned',
     FALSE, FALSE, FALSE, '{}'::jsonb)
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

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    ('buddy', 'Buddy',
     'Maintain memory, surface operational events, and perform low-risk housekeeping.',
     'T2', 'active', TRUE, '60s', 'com.jarvis.alpha.buddy',
     ARRAY[]::TEXT[], ARRAY['memory.write', 'buddy.events.write'], 0.0,
     '{}'::jsonb, '{}'::jsonb, '{}'::jsonb),
    ('dream_mode', 'Dream Mode',
     'Plan, review, and execute bounded overnight work through Temporal.',
     'T4', 'active', TRUE, 'on_demand', 'com.jarvis.alpha.temporal.worker',
     ARRAY['notes.search', 'tasks.create'], ARRAY['dream.execute', 'approval.request'], 1.0,
     '{"writes": "approval_queue", "allowlist_only": true}'::jsonb,
     '{}'::jsonb, '{}'::jsonb),
    ('ken_voice', 'Ken Voice',
     'Draft in Ken''s voice without autonomous sends or external side effects.',
     'T2', 'planned', FALSE, 'on_demand', NULL,
     ARRAY[]::TEXT[], ARRAY['notes.read'], 0.25,
     '{"side_effects": "blocked"}'::jsonb, '{}'::jsonb, '{}'::jsonb),
    ('network_watchdog', 'Network Watchdog',
     'Monitor UniFi WAN, switches, APs, and new-device events.',
     'T1', 'planned', FALSE, '30s', NULL,
     ARRAY['unifi.wan_status', 'unifi.clients', 'unifi.health_check'], ARRAY['network.read'], 0.0,
     '{}'::jsonb, '{}'::jsonb, '{}'::jsonb),
    ('inbox_watcher', 'Inbox Watcher',
     'Classify inbound Gmail and surface action-worthy threads.',
     'T2', 'planned', FALSE, '5m', NULL,
     ARRAY['gmail.search_threads', 'gmail.read_thread'], ARRAY['email.read'], 0.50,
     '{"send": "blocked_until_wave_7"}'::jsonb, '{}'::jsonb, '{}'::jsonb),
    ('family_concierge', 'Family Concierge',
     'Route child-facing requests through age, scope, and parent-visibility controls.',
     'T3', 'planned', FALSE, 'per_request', NULL,
     ARRAY[]::TEXT[], ARRAY['child.ask', 'child.activity.write'], 0.25,
     '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)
ON CONFLICT (agent_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    purpose = EXCLUDED.purpose,
    risk_tier = EXCLUDED.risk_tier,
    status = EXCLUDED.status,
    enabled = EXCLUDED.enabled,
    cadence = EXCLUDED.cadence,
    launch_label = EXCLUDED.launch_label,
    allowed_skills = EXCLUDED.allowed_skills,
    allowed_scopes = EXCLUDED.allowed_scopes,
    cost_daily_cap_usd = EXCLUDED.cost_daily_cap_usd,
    approval_policy = EXCLUDED.approval_policy,
    model_policy = EXCLUDED.model_policy,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

DO $$
DECLARE
    v_skill_count integer;
    v_agent_count integer;
BEGIN
    SELECT COUNT(*) INTO v_skill_count FROM public.alpha_skill_registry;
    SELECT COUNT(*) INTO v_agent_count FROM public.alpha_agents;

    IF v_skill_count < 10 THEN
        RAISE EXCEPTION 'POST-FLIGHT registry seed FAILED: expected >=10 skills, got %', v_skill_count;
    END IF;
    IF v_agent_count < 4 THEN
        RAISE EXCEPTION 'POST-FLIGHT registry seed FAILED: expected >=4 agents, got %', v_agent_count;
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_policies
         WHERE schemaname = 'public'
           AND tablename = 'alpha_agents'
           AND policyname = 'agents_admin_write'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT registry RLS FAILED: agents_admin_write policy missing';
    END IF;

    RAISE NOTICE 'POST-FLIGHT registry seed OK: skills=% agents=%', v_skill_count, v_agent_count;
END $$;
