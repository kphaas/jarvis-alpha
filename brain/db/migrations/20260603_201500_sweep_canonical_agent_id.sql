-- Migration: 20260603_201500_sweep_canonical_agent_id
-- Purpose: Make Sweep the canonical network security agent id while preserving
--          historical runs/events and API compatibility in application code.

INSERT INTO public.alpha_agents (
    agent_id, display_name, purpose, risk_tier, status, enabled, owner, cadence,
    launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
    model_policy, approval_policy, metadata, created_at, updated_at
)
SELECT
    'sweep', display_name, purpose, risk_tier, status, enabled, owner, cadence,
    launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
    model_policy, approval_policy,
    metadata || '{"legacy_agent_id": "network_watchdog"}'::jsonb - 'display_alias',
    created_at, NOW()
FROM public.alpha_agents
WHERE agent_id = 'network_watchdog'
ON CONFLICT (agent_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    purpose = EXCLUDED.purpose,
    risk_tier = EXCLUDED.risk_tier,
    status = EXCLUDED.status,
    enabled = EXCLUDED.enabled,
    cadence = EXCLUDED.cadence,
    launch_label = EXCLUDED.launch_label,
    allowed_skills = EXCLUDED.allowed_skills,
    allowed_scopes = EXCLUDED.allowed_scopes,
    cost_daily_cap_usd = EXCLUDED.cost_daily_cap_usd,
    model_policy = EXCLUDED.model_policy,
    approval_policy = EXCLUDED.approval_policy,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

UPDATE public.alpha_agent_runs
SET agent_id = 'sweep'
WHERE agent_id = 'network_watchdog';

UPDATE public.alpha_agent_events
SET agent_id = 'sweep'
WHERE agent_id = 'network_watchdog';

DELETE FROM public.alpha_agents
WHERE agent_id = 'network_watchdog';

UPDATE public.alpha_agents
SET metadata = jsonb_set(
        jsonb_set(
            metadata,
            '{managed_agents}',
            '["porchlight","keyturner","sweep","tripwire","ledger"]'::jsonb,
            true
        ),
        '{agent_roles}',
        '{"porchlight":"posture_sweep","keyturner":"credential_rotation","sweep":"network_sweep","tripwire":"honeypot_sensor","ledger":"evidence_reporter"}'::jsonb,
        true
    ),
    updated_at = NOW()
WHERE agent_id = 'warden';

UPDATE public.alpha_skill_registry
SET metadata = metadata || '{"owner_agent": "sweep"}'::jsonb - 'display_alias',
    updated_at = NOW()
WHERE skill_name IN (
    'unifi.quarantine_recommendation',
    'unifi.firmware_drift',
    'unifi.wan_failover_health'
);

DO $$
DECLARE
    v_sweep_count integer;
    v_old_count integer;
    v_child_count integer;
    v_managed jsonb;
    v_skill_count integer;
BEGIN
    SELECT COUNT(*) INTO v_sweep_count
    FROM public.alpha_agents
    WHERE agent_id = 'sweep'
      AND display_name = 'Sweep'
      AND enabled = TRUE
      AND status = 'active';

    SELECT COUNT(*) INTO v_old_count
    FROM public.alpha_agents
    WHERE agent_id = 'network_watchdog';

    SELECT COUNT(*) INTO v_child_count
    FROM public.alpha_agent_runs
    WHERE agent_id = 'network_watchdog';

    SELECT v_child_count + COUNT(*) INTO v_child_count
    FROM public.alpha_agent_events
    WHERE agent_id = 'network_watchdog';

    SELECT metadata->'managed_agents' INTO v_managed
    FROM public.alpha_agents
    WHERE agent_id = 'warden';

    SELECT COUNT(*) INTO v_skill_count
    FROM public.alpha_skill_registry
    WHERE skill_name IN (
        'unifi.quarantine_recommendation',
        'unifi.firmware_drift',
        'unifi.wan_failover_health'
    )
      AND metadata->>'owner_agent' = 'sweep';

    IF v_sweep_count <> 1
       OR v_old_count <> 0
       OR v_child_count <> 0
       OR NOT (v_managed ? 'sweep')
       OR (v_managed ? 'network_watchdog')
       OR v_skill_count <> 3 THEN
        RAISE EXCEPTION 'POST-FLIGHT Sweep canonical agent id FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Sweep canonical agent id OK';
END $$;
