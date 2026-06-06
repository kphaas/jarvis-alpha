-- Migration: 20260606_091500_sentry_data_boundary_agent
-- Purpose:   Register Sentry as Warden's read-only data-boundary monitor.
--            This adds no new write powers and performs no remediation.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('sentry.boundary_inventory', 'sentry', 'boundary_inventory',
     'Inventory Alpha, Brain, Family, Financial, Forge, Cloudflare, and Tailscale data boundaries.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "sentry", "saved_for_later": true}'::jsonb),
    ('sentry.cross_system_flow_review', 'sentry', 'cross_system_flow_review',
     'Review cross-system data flows for unexpected Family, Alpha, Brain, Forge, or Financial exposure.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "sentry", "saved_for_later": true}'::jsonb),
    ('sentry.pii_log_boundary_scan', 'sentry', 'pii_log_boundary_scan',
     'Scan structured logs and agent events for PII, child data, or financial data crossing approved boundaries.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "sentry", "saved_for_later": true}'::jsonb)
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
    metadata = public.alpha_skill_registry.metadata || EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    ('sentry', 'Sentry',
     'Monitor cross-system data boundaries so Family, Alpha, Brain, Forge, and Financial data stay in approved zones.',
     'T2', 'active', TRUE, 'on_demand', NULL,
     ARRAY[
       'sentry.boundary_inventory',
       'sentry.cross_system_flow_review',
       'sentry.pii_log_boundary_scan',
       'notify.send'
     ],
     ARRAY[
       'security.read',
       'agents.read',
       'logs.read',
       'evidence.read',
       'notify.send'
     ],
     0.0,
     '{"writes": "notification_only", "remediation": "blocked"}'::jsonb,
     '{}'::jsonb,
     '{
        "mattermost_channel_key": "security_alerts",
        "manual_run_enabled": false,
        "warden_managed": true,
        "warden_role": "data_boundary_monitor",
        "monitors": [
          "family_external_boundary",
          "alpha_financial_boundary",
          "brain_data_boundary",
          "forge_code_boundary",
          "pii_log_boundary",
          "cloudflare_access_boundary",
          "tailscale_acl_boundary"
        ],
        "protected_domains": [
          "family",
          "alpha",
          "brain",
          "forge",
          "financial"
        ],
        "capabilities": [
          "boundary_inventory",
          "cross_system_flow_review",
          "pii_log_boundary_scan"
        ],
        "planned_skills": [
          "sentry.boundary_inventory",
          "sentry.cross_system_flow_review",
          "sentry.pii_log_boundary_scan"
        ],
        "remediation": "alert_only"
      }'::jsonb)
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
    metadata = public.alpha_agents.metadata || EXCLUDED.metadata,
    updated_at = NOW();

UPDATE public.alpha_agents
SET metadata = jsonb_set(
    jsonb_set(
      jsonb_set(
        metadata,
        '{managed_agents}',
        (
          SELECT jsonb_agg(DISTINCT item)
          FROM jsonb_array_elements_text(
            COALESCE(metadata->'managed_agents', '[]'::jsonb) ||
            '["sentry"]'::jsonb
          ) AS t(item)
        ),
        true
      ),
      '{agent_roles}',
      COALESCE(metadata->'agent_roles', '{}'::jsonb)
      || '{"sentry": "data_boundary_monitor"}'::jsonb,
      true
    ),
    '{active_security_capabilities}',
    (
      SELECT jsonb_agg(DISTINCT item)
      FROM jsonb_array_elements_text(
        COALESCE(metadata->'active_security_capabilities', '[]'::jsonb) ||
        '[
          "sentry_boundary_inventory",
          "sentry_cross_system_flow_review",
          "sentry_pii_log_boundary_scan"
        ]'::jsonb
      ) AS t(item)
    ),
    true
)
WHERE agent_id = 'warden';

DO $$
DECLARE
    v_sentry jsonb;
    v_warden jsonb;
BEGIN
    SELECT metadata INTO v_sentry
    FROM public.alpha_agents
    WHERE agent_id = 'sentry';

    SELECT metadata INTO v_warden
    FROM public.alpha_agents
    WHERE agent_id = 'warden';

    IF v_sentry IS NULL
       OR v_sentry->>'warden_role' != 'data_boundary_monitor'
       OR NOT (v_sentry->'protected_domains' ? 'financial')
       OR NOT (v_warden->'managed_agents' ? 'sentry')
       OR NOT (v_warden->'active_security_capabilities' ? 'sentry_boundary_inventory') THEN
        RAISE EXCEPTION 'POST-FLIGHT sentry data boundary agent registration FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT sentry data boundary agent registration OK';
END $$;
