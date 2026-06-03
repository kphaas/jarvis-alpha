-- Migration: 20260603_160000_tripwire_honeypot_agent
-- Purpose: Register Tripwire as Warden's honeypot sensor.

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    ('tripwire', 'Tripwire',
     'Monitor honeypot traps, classify suspicious hits, and escalate findings to Warden.',
     'T1', 'active', TRUE, 'event_driven', NULL,
     ARRAY['notify.send'],
     ARRAY['security.read', 'notify.send'],
     0.0,
     '{"writes": "notification_only", "remediation": "blocked"}'::jsonb,
     '{}'::jsonb,
     '{
        "mattermost_channel_key": "security_alerts",
        "manual_run_enabled": false,
        "warden_managed": true,
        "warden_role": "honeypot_sensor",
        "monitors": ["honeypot_hits", "trap_paths", "source_patterns"],
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
SET metadata = metadata || '{
      "managed_agents": ["porchlight", "keyturner", "network_watchdog", "tripwire"],
      "agent_roles": {
        "porchlight": "posture_sweep",
        "keyturner": "credential_rotation",
        "network_watchdog": "network_sweep",
        "tripwire": "honeypot_sensor"
      }
    }'::jsonb,
    updated_at = NOW()
WHERE agent_id = 'warden';

DO $$
DECLARE
    v_tripwire_count integer;
    v_managed text[];
    v_role text;
BEGIN
    SELECT COUNT(*)
    INTO v_tripwire_count
    FROM public.alpha_agents
    WHERE agent_id = 'tripwire'
      AND display_name = 'Tripwire'
      AND enabled
      AND status = 'active'
      AND metadata->>'warden_role' = 'honeypot_sensor'
      AND metadata->>'mattermost_channel_key' = 'security_alerts';

    SELECT ARRAY(
        SELECT jsonb_array_elements_text(metadata->'managed_agents')
        FROM public.alpha_agents
        WHERE agent_id = 'warden'
    )
    INTO v_managed;

    SELECT metadata #>> '{agent_roles,tripwire}'
    INTO v_role
    FROM public.alpha_agents
    WHERE agent_id = 'warden';

    IF v_tripwire_count <> 1
       OR NOT ('tripwire' = ANY(v_managed))
       OR v_role IS DISTINCT FROM 'honeypot_sensor' THEN
        RAISE EXCEPTION 'POST-FLIGHT Tripwire registry seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Tripwire registry seed OK';
END $$;
