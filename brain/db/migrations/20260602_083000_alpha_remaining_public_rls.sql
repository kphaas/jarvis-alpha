-- Close the remaining public-table RLS gaps surfaced by Porchlight.
--
-- Policy shape:
--   * System/config/cost/profile tables: platform_admin only.
--   * Append-style logs/ledgers: platform_admin SELECT/INSERT; no UPDATE/DELETE.
--   * jarvis_request_log: platform_admin SELECT/INSERT; request-owned INSERT.
--   * Vault chunks/permissions: inherit document visibility for reads, admin for writes.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(2026060201);

DO $preflight$
DECLARE
    expected_tables TEXT[] := ARRAY[
        'alpha_approval_audit_quarantine',
        'alpha_briefings',
        'alpha_budget_config',
        'alpha_cloud_costs',
        'alpha_credit_balance',
        'alpha_dream_allowed_paths',
        'alpha_hardware_config',
        'alpha_honeypot_events',
        'alpha_model_pricing',
        'alpha_node_registry',
        'alpha_overnight_approvals',
        'alpha_perplexity_credit',
        'alpha_power_config',
        'alpha_power_daily',
        'alpha_power_hourly',
        'alpha_power_readings',
        'alpha_profiles',
        'alpha_projects',
        'alpha_prompt_registry',
        'alpha_secret_rotations',
        'alpha_subscriptions',
        'alpha_users',
        'alpha_workspace_users',
        'alpha_workspaces',
        'jarvis_request_log',
        'pipeline_lessons',
        'pipeline_metrics_brain',
        'pipeline_trust_scores',
        'secret_access_log',
        'vault_chunks',
        'vault_document_permissions'
    ];
    missing TEXT[];
BEGIN
    SELECT array_agg(t.table_name ORDER BY t.table_name)
      INTO missing
      FROM unnest(expected_tables) AS t(table_name)
     WHERE NOT EXISTS (
        SELECT 1
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relkind = 'r'
           AND c.relname = t.table_name
     );

    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'alpha remaining RLS preflight failed; missing tables: %', missing;
    END IF;
END
$preflight$;

DO $admin_tables$
DECLARE
    tbl TEXT;
    admin_tables TEXT[] := ARRAY[
        'alpha_approval_audit_quarantine',
        'alpha_briefings',
        'alpha_budget_config',
        'alpha_cloud_costs',
        'alpha_credit_balance',
        'alpha_dream_allowed_paths',
        'alpha_hardware_config',
        'alpha_model_pricing',
        'alpha_node_registry',
        'alpha_overnight_approvals',
        'alpha_perplexity_credit',
        'alpha_power_config',
        'alpha_power_daily',
        'alpha_power_hourly',
        'alpha_power_readings',
        'alpha_profiles',
        'alpha_projects',
        'alpha_prompt_registry',
        'alpha_subscriptions',
        'alpha_users',
        'alpha_workspace_users',
        'alpha_workspaces',
        'pipeline_lessons',
        'pipeline_metrics_brain',
        'pipeline_trust_scores'
    ];
BEGIN
    FOREACH tbl IN ARRAY admin_tables LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', tbl || '_platform_admin', tbl);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I AS PERMISSIVE FOR ALL USING (current_setting(''rls.role'', true) = ''platform_admin'') WITH CHECK (current_setting(''rls.role'', true) = ''platform_admin'')',
            tbl || '_platform_admin',
            tbl
        );
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', tbl);
    END LOOP;
END
$admin_tables$;

-- Append-style security telemetry: readable/writable only by explicit platform-admin context.
-- alpha_cloud_costs already has a canonical platform-admin policy; it was missing FORCE.
ALTER TABLE public.alpha_cloud_costs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_cloud_costs FORCE ROW LEVEL SECURITY;

ALTER TABLE public.alpha_honeypot_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS alpha_honeypot_events_admin_select ON public.alpha_honeypot_events;
DROP POLICY IF EXISTS alpha_honeypot_events_admin_insert ON public.alpha_honeypot_events;
CREATE POLICY alpha_honeypot_events_admin_select ON public.alpha_honeypot_events
    AS PERMISSIVE FOR SELECT
    USING (current_setting('rls.role', true) = 'platform_admin');
CREATE POLICY alpha_honeypot_events_admin_insert ON public.alpha_honeypot_events
    AS PERMISSIVE FOR INSERT
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
ALTER TABLE public.alpha_honeypot_events FORCE ROW LEVEL SECURITY;

ALTER TABLE public.alpha_secret_rotations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS alpha_secret_rotations_admin_select ON public.alpha_secret_rotations;
DROP POLICY IF EXISTS alpha_secret_rotations_admin_insert ON public.alpha_secret_rotations;
CREATE POLICY alpha_secret_rotations_admin_select ON public.alpha_secret_rotations
    AS PERMISSIVE FOR SELECT
    USING (current_setting('rls.role', true) = 'platform_admin');
CREATE POLICY alpha_secret_rotations_admin_insert ON public.alpha_secret_rotations
    AS PERMISSIVE FOR INSERT
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
ALTER TABLE public.alpha_secret_rotations FORCE ROW LEVEL SECURITY;

ALTER TABLE public.secret_access_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS secret_access_log_admin_select ON public.secret_access_log;
DROP POLICY IF EXISTS secret_access_log_admin_insert ON public.secret_access_log;
CREATE POLICY secret_access_log_admin_select ON public.secret_access_log
    AS PERMISSIVE FOR SELECT
    USING (current_setting('rls.role', true) = 'platform_admin');
CREATE POLICY secret_access_log_admin_insert ON public.secret_access_log
    AS PERMISSIVE FOR INSERT
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
ALTER TABLE public.secret_access_log FORCE ROW LEVEL SECURITY;

ALTER TABLE public.jarvis_request_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS jarvis_request_log_admin_select ON public.jarvis_request_log;
DROP POLICY IF EXISTS jarvis_request_log_admin_insert ON public.jarvis_request_log;
DROP POLICY IF EXISTS jarvis_request_log_own_insert ON public.jarvis_request_log;
CREATE POLICY jarvis_request_log_admin_select ON public.jarvis_request_log
    AS PERMISSIVE FOR SELECT
    USING (current_setting('rls.role', true) = 'platform_admin');
CREATE POLICY jarvis_request_log_admin_insert ON public.jarvis_request_log
    AS PERMISSIVE FOR INSERT
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
CREATE POLICY jarvis_request_log_own_insert ON public.jarvis_request_log
    AS PERMISSIVE FOR INSERT
    WITH CHECK (user_id = current_setting('rls.user_id', true));
ALTER TABLE public.jarvis_request_log FORCE ROW LEVEL SECURITY;

-- Vault chunks inherit readable document visibility. Writes remain platform-admin only.
ALTER TABLE public.vault_chunks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS vault_chunks_platform_admin ON public.vault_chunks;
DROP POLICY IF EXISTS vault_chunks_visible_document_select ON public.vault_chunks;
CREATE POLICY vault_chunks_platform_admin ON public.vault_chunks
    AS PERMISSIVE FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
CREATE POLICY vault_chunks_visible_document_select ON public.vault_chunks
    AS PERMISSIVE FOR SELECT
    USING (
        EXISTS (
            SELECT 1
              FROM public.vault_documents d
             WHERE d.id = vault_chunks.document_id
        )
    );
ALTER TABLE public.vault_chunks FORCE ROW LEVEL SECURITY;

-- Direct document permissions can be inspected by the grantee; only admins mutate.
ALTER TABLE public.vault_document_permissions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS vault_document_permissions_platform_admin ON public.vault_document_permissions;
DROP POLICY IF EXISTS vault_document_permissions_user_select ON public.vault_document_permissions;
CREATE POLICY vault_document_permissions_platform_admin ON public.vault_document_permissions
    AS PERMISSIVE FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
CREATE POLICY vault_document_permissions_user_select ON public.vault_document_permissions
    AS PERMISSIVE FOR SELECT
    USING (
        current_setting('rls.role', true) = 'user'
        AND user_id = current_setting('rls.user_id', true)
        AND (can_read OR can_search)
    );
ALTER TABLE public.vault_document_permissions FORCE ROW LEVEL SECURITY;

DO $postcheck$
DECLARE
    bad TEXT[];
BEGIN
    WITH target(table_name) AS (
        VALUES
            ('alpha_approval_audit_quarantine'), ('alpha_briefings'),
            ('alpha_budget_config'), ('alpha_cloud_costs'),
            ('alpha_credit_balance'),
            ('alpha_dream_allowed_paths'), ('alpha_hardware_config'),
            ('alpha_honeypot_events'), ('alpha_model_pricing'),
            ('alpha_node_registry'), ('alpha_overnight_approvals'),
            ('alpha_perplexity_credit'), ('alpha_power_config'),
            ('alpha_power_daily'), ('alpha_power_hourly'),
            ('alpha_power_readings'), ('alpha_profiles'),
            ('alpha_projects'), ('alpha_prompt_registry'),
            ('alpha_secret_rotations'), ('alpha_subscriptions'),
            ('alpha_users'), ('alpha_workspace_users'),
            ('alpha_workspaces'), ('jarvis_request_log'),
            ('pipeline_lessons'), ('pipeline_metrics_brain'),
            ('pipeline_trust_scores'), ('secret_access_log'),
            ('vault_chunks'), ('vault_document_permissions')
    )
    SELECT array_agg(t.table_name ORDER BY t.table_name)
      INTO bad
      FROM target t
      JOIN pg_class c ON c.relname = t.table_name
      JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
      LEFT JOIN (
        SELECT polrelid, count(*) AS policy_count
          FROM pg_policy
         GROUP BY polrelid
      ) p ON p.polrelid = c.oid
     WHERE NOT c.relrowsecurity
        OR NOT c.relforcerowsecurity
        OR COALESCE(p.policy_count, 0) = 0;

    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'alpha remaining RLS postcheck failed; unresolved tables: %', bad;
    END IF;
END
$postcheck$;

COMMIT;
