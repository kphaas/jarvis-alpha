-- Migration: 20260602_003500_porchlight_security_agent
-- Purpose:   Register Porchlight as Alpha's scheduled security sweep agent.

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    ('porchlight', 'Porchlight',
     'Run scheduled security posture sweeps and surface dangerous findings.',
     'T2', 'active', TRUE, 'daily', 'com.jarvis.alpha.porchlight',
     ARRAY['notify.send', 'notify.send_mattermost', 'notify.send_pushover'],
     ARRAY['notify.send', 'security.read'], 0.0,
     '{"writes": "notification_only", "remediation": "blocked"}'::jsonb,
     '{}'::jsonb,
     '{
        "mattermost_channel_key": "security_alerts",
        "report_path": "logs/porchlight_security_report.json",
        "manual_run_enabled": true
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

DO $$
DECLARE
    v_channel text;
BEGIN
    SELECT metadata->>'mattermost_channel_key'
    INTO v_channel
    FROM public.alpha_agents
    WHERE agent_id = 'porchlight'
      AND enabled
      AND status = 'active'
      AND 'notify.send' = ANY(allowed_skills);

    IF v_channel IS DISTINCT FROM 'security_alerts' THEN
        RAISE EXCEPTION 'POST-FLIGHT Porchlight registry seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Porchlight registry seed OK';
END $$;
