-- Migration: 20260526_015000_agent_runtime_network
-- Purpose:   Agent runtime SECDEF helpers, ChatOps smoke monitor seed, and
--            read-only UniFi health skill activation.

CREATE OR REPLACE FUNCTION public.start_agent_run(
    p_agent_id TEXT,
    p_trigger_type TEXT DEFAULT 'manual',
    p_trace_id TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'::jsonb
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_id UUID;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);

    IF NOT EXISTS (
        SELECT 1
        FROM public.alpha_agents
        WHERE agent_id = p_agent_id
          AND status = 'active'
          AND enabled = TRUE
    ) THEN
        RAISE EXCEPTION 'agent is not runnable: %', p_agent_id;
    END IF;

    INSERT INTO public.alpha_agent_runs (
        agent_id,
        status,
        trigger_type,
        trace_id,
        started_at,
        metadata
    )
    VALUES (
        p_agent_id,
        'running',
        p_trigger_type,
        p_trace_id,
        NOW(),
        COALESCE(p_metadata, '{}'::jsonb)
    )
    RETURNING id INTO v_id;

    UPDATE public.alpha_agents
    SET metadata = jsonb_set(metadata, '{last_run_started_at}', to_jsonb(NOW()::text), true),
        updated_at = NOW()
    WHERE agent_id = p_agent_id;

    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.finish_agent_run(
    p_run_id UUID,
    p_status TEXT,
    p_cost_usd NUMERIC DEFAULT 0,
    p_error_text TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'::jsonb
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_agent_id TEXT;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);

    IF p_status NOT IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'invalid agent run terminal status: %', p_status;
    END IF;
    IF p_cost_usd < 0 THEN
        RAISE EXCEPTION 'agent run cost must be non-negative';
    END IF;

    UPDATE public.alpha_agent_runs
    SET status = p_status,
        completed_at = NOW(),
        cost_usd = p_cost_usd,
        error_text = p_error_text,
        metadata = metadata || COALESCE(p_metadata, '{}'::jsonb)
    WHERE id = p_run_id
    RETURNING agent_id INTO v_agent_id;

    IF v_agent_id IS NULL THEN
        RAISE EXCEPTION 'agent run not found: %', p_run_id;
    END IF;

    UPDATE public.alpha_agents
    SET metadata = jsonb_set(
            jsonb_set(metadata, '{last_run_status}', to_jsonb(p_status), true),
            '{last_run_completed_at}', to_jsonb(NOW()::text), true
        ),
        updated_at = NOW()
    WHERE agent_id = v_agent_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_agent_due_run(
    p_agent_id TEXT,
    p_interval_seconds INTEGER
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_claimed BOOLEAN;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);

    IF p_interval_seconds <= 0 THEN
        RAISE EXCEPTION 'interval must be positive';
    END IF;

    WITH claimed AS (
        UPDATE public.alpha_agents
        SET metadata = jsonb_set(
                metadata,
                '{last_runtime_claim_at}',
                to_jsonb(NOW()::text),
                true
            ),
            updated_at = NOW()
        WHERE agent_id = p_agent_id
          AND status = 'active'
          AND enabled = TRUE
          AND (
              metadata->>'last_runtime_claim_at' IS NULL
              OR (metadata->>'last_runtime_claim_at')::timestamptz
                    <= NOW() - make_interval(secs => p_interval_seconds)
          )
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM claimed) INTO v_claimed;

    RETURN v_claimed;
END;
$$;

CREATE OR REPLACE FUNCTION public.update_agent_runtime_metadata(
    p_agent_id TEXT,
    p_metadata JSONB
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);

    UPDATE public.alpha_agents
    SET metadata = metadata || COALESCE(p_metadata, '{}'::jsonb),
        updated_at = NOW()
    WHERE agent_id = p_agent_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'agent not found: %', p_agent_id;
    END IF;
END;
$$;

GRANT EXECUTE ON FUNCTION public.start_agent_run(
    TEXT, TEXT, TEXT, JSONB
) TO jarvis_alpha_app, jarvis_alpha_writer;

GRANT EXECUTE ON FUNCTION public.finish_agent_run(
    UUID, TEXT, NUMERIC, TEXT, JSONB
) TO jarvis_alpha_app, jarvis_alpha_writer;

GRANT EXECUTE ON FUNCTION public.claim_agent_due_run(
    TEXT, INTEGER
) TO jarvis_alpha_app, jarvis_alpha_writer;

GRANT EXECUTE ON FUNCTION public.update_agent_runtime_metadata(
    TEXT, JSONB
) TO jarvis_alpha_app, jarvis_alpha_writer;

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('unifi.health_check', 'unifi', 'health_check',
     'Read controller, AP, and switch health signals.', 'T1', 'network.read', 'active',
     FALSE, FALSE, FALSE, '{"adapter": "gateway_unifi"}'::jsonb)
ON CONFLICT (skill_name) DO UPDATE
SET description = EXCLUDED.description,
    approval_tier = EXCLUDED.approval_tier,
    scope = EXCLUDED.scope,
    status = EXCLUDED.status,
    mutates_state = EXCLUDED.mutates_state,
    body_access = EXCLUDED.body_access,
    idempotency_required = EXCLUDED.idempotency_required,
    metadata = alpha_skill_registry.metadata || EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    ('chatops_smoke', 'ChatOps Smoke',
     'Post a scheduled low-risk Mattermost smoke event so the operator can trust the notification path.',
     'T1', 'active', TRUE, '6h', NULL,
     ARRAY['notify.send', 'notify.send_mattermost', 'notify.send_pushover'],
     ARRAY['notify.send'], 0.0,
     '{"writes": "notification_only"}'::jsonb,
     '{}'::jsonb,
     '{"mattermost_channel_key": "alpha_events", "smoke_interval_seconds": 21600}'::jsonb),
    ('network_watchdog', 'Network Watchdog',
     'Monitor UniFi WAN, switches, APs, and new-device events.',
     'T1', 'active', FALSE, '30s', NULL,
     ARRAY['unifi.wan_status', 'unifi.clients', 'unifi.health_check', 'notify.send'],
     ARRAY['network.read', 'notify.send'], 0.0,
     '{"writes": "notification_only", "remediation": "blocked"}'::jsonb,
     '{}'::jsonb,
     '{"mattermost_channel_key": "alpha_events", "poll_interval_seconds": 30}'::jsonb)
ON CONFLICT (agent_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    purpose = EXCLUDED.purpose,
    risk_tier = EXCLUDED.risk_tier,
    status = EXCLUDED.status,
    cadence = EXCLUDED.cadence,
    launch_label = EXCLUDED.launch_label,
    allowed_skills = EXCLUDED.allowed_skills,
    allowed_scopes = EXCLUDED.allowed_scopes,
    cost_daily_cap_usd = EXCLUDED.cost_daily_cap_usd,
    approval_policy = EXCLUDED.approval_policy,
    model_policy = EXCLUDED.model_policy,
    metadata = alpha_agents.metadata || EXCLUDED.metadata,
    updated_at = NOW();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE proname = 'start_agent_run'
          AND pronamespace = 'public'::regnamespace
          AND pg_get_functiondef(oid) LIKE '%set_config(''rls.role'', ''platform_admin'', true)%'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT start_agent_run SECDEF FAILED';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.alpha_skill_registry
        WHERE skill_name = 'unifi.health_check'
          AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT unifi.health_check activation FAILED';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.alpha_agents
        WHERE agent_id = 'chatops_smoke'
          AND status = 'active'
          AND enabled = TRUE
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT chatops_smoke seed FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT agent runtime + network seed OK';
END $$;
