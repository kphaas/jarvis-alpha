-- Warden is the coordinating security agent. Sweep is the user-facing name for
-- the existing network_watchdog agent_id so historical runs/events remain intact.

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    ('warden', 'Warden',
     'Coordinate Alpha security agents, summarize posture, and route remediation to the right owner.',
     'T2', 'active', TRUE, 'continuous', NULL,
     ARRAY['notify.send'],
     ARRAY['security.read', 'agents.read', 'notify.send'],
     0.0,
     '{"writes": "notification_only", "remediation": "delegated"}'::jsonb,
     '{}'::jsonb,
     '{
        "mattermost_channel_key": "security_alerts",
        "manual_run_enabled": false,
        "managed_agents": ["porchlight", "keyturner", "network_watchdog"],
        "agent_roles": {
          "porchlight": "posture_sweep",
          "keyturner": "credential_rotation",
          "network_watchdog": "network_sweep"
        },
        "next_network_hardening": "unifi_cert_pinning"
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
SET display_name = 'Sweep',
    purpose = 'Monitor UniFi WAN, switches, APs, new-device events, and network trust hardening.',
    metadata = metadata || '{
      "warden_managed": true,
      "warden_role": "network_sweep",
      "display_alias": "Sweep",
      "next_hardening": "unifi_cert_pinning"
    }'::jsonb,
    updated_at = NOW()
WHERE agent_id = 'network_watchdog';

UPDATE public.alpha_agents
SET metadata = metadata || '{
      "warden_managed": true,
      "warden_role": "posture_sweep"
    }'::jsonb,
    updated_at = NOW()
WHERE agent_id = 'porchlight';

UPDATE public.alpha_agents
SET metadata = metadata || '{
      "warden_managed": true,
      "warden_role": "credential_rotation"
    }'::jsonb,
    updated_at = NOW()
WHERE agent_id = 'keyturner';

DO $$
DECLARE
    v_warden_count integer;
    v_sweep_name text;
    v_managed text[];
BEGIN
    SELECT COUNT(*)
    INTO v_warden_count
    FROM public.alpha_agents
    WHERE agent_id = 'warden'
      AND enabled
      AND status = 'active';

    SELECT display_name
    INTO v_sweep_name
    FROM public.alpha_agents
    WHERE agent_id = 'network_watchdog';

    SELECT ARRAY(
        SELECT jsonb_array_elements_text(metadata->'managed_agents')
        FROM public.alpha_agents
        WHERE agent_id = 'warden'
    )
    INTO v_managed;

    IF v_warden_count <> 1
       OR v_sweep_name IS DISTINCT FROM 'Sweep'
       OR NOT ('porchlight' = ANY(v_managed))
       OR NOT ('keyturner' = ANY(v_managed))
       OR NOT ('network_watchdog' = ANY(v_managed)) THEN
        RAISE EXCEPTION 'POST-FLIGHT Warden/Sweep registry seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Warden/Sweep registry seed OK';
END $$;
