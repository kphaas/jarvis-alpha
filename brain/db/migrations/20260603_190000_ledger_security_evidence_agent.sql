-- Migration: 20260603_190000_ledger_security_evidence_agent
-- Purpose: Register Ledger as Warden's security-evidence reporter and save
--          planned security skills for future Porchlight/Sweep/Keyturner/
--          Tripwire/Warden work without enabling new automation.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('evidence.package_report', 'evidence', 'package_report',
     'Package security events, access changes, Cloudflare drift, and key rotations into a tamper-evident report.',
     'T2', 'evidence.read', 'planned', FALSE, FALSE, FALSE,
     '{
        "owner_agent": "ledger",
        "planned_for": "security_evidence_reports",
        "evidence_sources": [
          "security_events",
          "family_access_changes",
          "cloudflare_access_changes",
          "key_rotation_history"
        ],
        "tamper_evidence": "hash_chain_planned"
      }'::jsonb),
    ('dependencies.scan', 'dependencies', 'scan',
     'Summarize dependency and static-security scan findings for Porchlight.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "porchlight", "saved_for_later": true}'::jsonb),
    ('cloudflare.policy_drift', 'cloudflare', 'policy_drift',
     'Detect Cloudflare Access application and policy drift for Porchlight.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "porchlight", "saved_for_later": true}'::jsonb),
    ('github.branch_protection_drift', 'github', 'branch_protection_drift',
     'Detect GitHub branch protection and required-check drift for Porchlight.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "porchlight", "saved_for_later": true}'::jsonb),
    ('unifi.quarantine_recommendation', 'unifi', 'quarantine_recommendation',
     'Recommend quarantine actions for unknown UniFi devices without mutating network state.',
     'T1', 'network.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "network_watchdog", "display_alias": "Sweep", "saved_for_later": true}'::jsonb),
    ('unifi.firmware_drift', 'unifi', 'firmware_drift',
     'Detect UniFi gateway, switch, and AP firmware drift for Sweep.',
     'T1', 'network.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "network_watchdog", "display_alias": "Sweep", "saved_for_later": true}'::jsonb),
    ('unifi.wan_failover_health', 'unifi', 'wan_failover_health',
     'Check WAN failover readiness and health for Sweep.',
     'T1', 'network.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "network_watchdog", "display_alias": "Sweep", "saved_for_later": true}'::jsonb),
    ('keyturner.oauth_health', 'keyturner', 'oauth_health',
     'Check OAuth refresh-token health and expiry risk for Keyturner.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "keyturner", "saved_for_later": true}'::jsonb),
    ('keyturner.rotation_dry_run', 'keyturner', 'rotation_dry_run',
     'Dry-run a credential rotation plan without changing secrets.',
     'T2', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "keyturner", "saved_for_later": true}'::jsonb),
    ('keyturner.secrets_forecast', 'keyturner', 'secrets_forecast',
     'Forecast upcoming secret rotation deadlines for Keyturner.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "keyturner", "saved_for_later": true}'::jsonb),
    ('tripwire.source_reputation', 'tripwire', 'source_reputation',
     'Enrich Tripwire honeypot sources with local reputation and repeat-offender context.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "tripwire", "saved_for_later": true}'::jsonb),
    ('tripwire.probe_clustering', 'tripwire', 'probe_clustering',
     'Cluster repeated scanner probes across Tripwire trap paths.',
     'T1', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "tripwire", "saved_for_later": true}'::jsonb),
    ('warden.weekly_brief', 'warden', 'weekly_brief',
     'Prepare a weekly Warden security posture brief.',
     'T2', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "warden", "saved_for_later": true}'::jsonb),
    ('warden.auto_ticket', 'warden', 'auto_ticket',
     'Create an operator-visible ticket for a Warden security gap.',
     'T3', 'tasks.write', 'planned', TRUE, FALSE, TRUE,
     '{"owner_agent": "warden", "saved_for_later": true}'::jsonb),
    ('warden.owner_routing', 'warden', 'owner_routing',
     'Route a security gap to the correct security agent owner.',
     'T2', 'security.read', 'planned', FALSE, FALSE, FALSE,
     '{"owner_agent": "warden", "saved_for_later": true}'::jsonb)
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
    ('ledger', 'Ledger',
     'Package security evidence, access changes, Cloudflare drift, and key rotations into tamper-evident reports.',
     'T2', 'active', TRUE, 'on_demand', NULL,
     ARRAY['evidence.package_report', 'notify.send'],
     ARRAY['security.read', 'agents.read', 'evidence.read', 'notify.send'],
     0.0,
     '{"writes": "report_only", "remediation": "blocked"}'::jsonb,
     '{}'::jsonb,
     '{
        "mattermost_channel_key": "security_alerts",
        "manual_run_enabled": false,
        "warden_managed": true,
        "warden_role": "evidence_reporter",
        "report_mode": "tamper_evident",
        "capabilities": [
          "security_event_packaging",
          "family_access_change_evidence",
          "cloudflare_access_change_evidence",
          "key_rotation_evidence",
          "hash_chained_report_manifest"
        ],
        "evidence_sources": [
          "alpha_agent_events",
          "alpha_agent_runs",
          "cloudflare_access_audit",
          "keyturner_rotation_ledger",
          "family_external_access_changes"
        ],
        "remediation": "evidence_only"
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
SET metadata = metadata
    || jsonb_build_object(
        'managed_agents',
        jsonb_build_array(
            'porchlight',
            'keyturner',
            'network_watchdog',
            'tripwire',
            'ledger'
        ),
        'agent_roles',
        COALESCE(metadata->'agent_roles', '{}'::jsonb)
        || '{
             "porchlight": "posture_sweep",
             "keyturner": "credential_rotation",
             "network_watchdog": "network_sweep",
             "tripwire": "honeypot_sensor",
             "ledger": "evidence_reporter"
           }'::jsonb,
        'planned_skills',
        jsonb_build_array(
            'warden.weekly_brief',
            'warden.auto_ticket',
            'warden.owner_routing'
        )
    ),
    updated_at = NOW()
WHERE agent_id = 'warden';

UPDATE public.alpha_agents
SET metadata = metadata || jsonb_build_object(
        'planned_skills',
        jsonb_build_array(
            'dependencies.scan',
            'cloudflare.policy_drift',
            'github.branch_protection_drift'
        )
    ),
    updated_at = NOW()
WHERE agent_id = 'porchlight';

UPDATE public.alpha_agents
SET metadata = metadata || jsonb_build_object(
        'planned_skills',
        jsonb_build_array(
            'keyturner.oauth_health',
            'keyturner.rotation_dry_run',
            'keyturner.secrets_forecast'
        )
    ),
    updated_at = NOW()
WHERE agent_id = 'keyturner';

UPDATE public.alpha_agents
SET metadata = metadata || jsonb_build_object(
        'planned_skills',
        jsonb_build_array(
            'unifi.quarantine_recommendation',
            'unifi.firmware_drift',
            'unifi.wan_failover_health'
        )
    ),
    updated_at = NOW()
WHERE agent_id = 'network_watchdog';

UPDATE public.alpha_agents
SET metadata = metadata || jsonb_build_object(
        'planned_skills',
        jsonb_build_array(
            'tripwire.source_reputation',
            'tripwire.probe_clustering'
        )
    ),
    updated_at = NOW()
WHERE agent_id = 'tripwire';

DO $$
DECLARE
    v_ledger_count integer;
    v_managed text[];
    v_planned_count integer;
BEGIN
    SELECT COUNT(*)
    INTO v_ledger_count
    FROM public.alpha_agents
    WHERE agent_id = 'ledger'
      AND display_name = 'Ledger'
      AND enabled
      AND status = 'active'
      AND metadata->>'warden_role' = 'evidence_reporter'
      AND metadata->>'mattermost_channel_key' = 'security_alerts';

    SELECT ARRAY(
        SELECT jsonb_array_elements_text(metadata->'managed_agents')
        FROM public.alpha_agents
        WHERE agent_id = 'warden'
    )
    INTO v_managed;

    SELECT COUNT(*)
    INTO v_planned_count
    FROM public.alpha_skill_registry
    WHERE metadata->>'saved_for_later' = 'true'
       OR metadata->>'owner_agent' = 'ledger';

    IF v_ledger_count <> 1
       OR NOT ('ledger' = ANY(v_managed))
       OR v_planned_count < 15 THEN
        RAISE EXCEPTION 'POST-FLIGHT Ledger registry seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Ledger registry seed OK';
END $$;
