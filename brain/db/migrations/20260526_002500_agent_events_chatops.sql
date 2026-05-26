-- Migration: 20260526_002500_agent_events_chatops
-- Purpose:   Harden agent event persistence and enable Mattermost read-only
--            ChatOps commands without making Mattermost the internal bus.

ALTER TABLE public.alpha_agent_events
    ADD COLUMN IF NOT EXISTS title TEXT,
    ADD COLUMN IF NOT EXISTS correlation_id TEXT,
    ADD COLUMN IF NOT EXISTS channel_key TEXT NOT NULL DEFAULT 'alpha_events',
    ADD COLUMN IF NOT EXISTS notification_status TEXT NOT NULL DEFAULT 'not_requested',
    ADD COLUMN IF NOT EXISTS notification_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS notification_error TEXT,
    ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;

UPDATE public.alpha_agent_events
SET title = LEFT(message, 250)
WHERE title IS NULL;

ALTER TABLE public.alpha_agent_events
    ALTER COLUMN title SET NOT NULL;

ALTER TABLE public.alpha_agent_events
    DROP CONSTRAINT IF EXISTS alpha_agent_events_severity_check;

ALTER TABLE public.alpha_agent_events
    ADD CONSTRAINT alpha_agent_events_severity_check
    CHECK (severity IN ('debug', 'info', 'needs_input', 'warning', 'error', 'critical'));

ALTER TABLE public.alpha_agent_events
    DROP CONSTRAINT IF EXISTS alpha_agent_events_channel_key_check;

ALTER TABLE public.alpha_agent_events
    ADD CONSTRAINT alpha_agent_events_channel_key_check
    CHECK (channel_key ~ '^[a-z][a-z0-9_]{0,31}$');

ALTER TABLE public.alpha_agent_events
    DROP CONSTRAINT IF EXISTS alpha_agent_events_notification_status_check;

ALTER TABLE public.alpha_agent_events
    ADD CONSTRAINT alpha_agent_events_notification_status_check
    CHECK (
        notification_status IN (
            'not_requested',
            'pending',
            'sent',
            'fallback_sent',
            'skipped',
            'denied',
            'failed'
        )
    );

CREATE INDEX IF NOT EXISTS idx_alpha_agent_events_correlation
    ON public.alpha_agent_events(correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.record_agent_event(
    p_agent_id TEXT,
    p_event_type TEXT,
    p_title TEXT,
    p_message TEXT,
    p_severity TEXT DEFAULT 'info',
    p_payload JSONB DEFAULT '{}'::jsonb,
    p_run_id UUID DEFAULT NULL,
    p_correlation_id TEXT DEFAULT NULL,
    p_channel_key TEXT DEFAULT 'alpha_events',
    p_notification_status TEXT DEFAULT 'not_requested'
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

    INSERT INTO public.alpha_agent_events (
        agent_id,
        run_id,
        event_type,
        severity,
        title,
        message,
        payload,
        correlation_id,
        channel_key,
        notification_status
    )
    VALUES (
        p_agent_id,
        p_run_id,
        p_event_type,
        p_severity,
        p_title,
        p_message,
        COALESCE(p_payload, '{}'::jsonb),
        p_correlation_id,
        p_channel_key,
        p_notification_status
    )
    RETURNING id INTO v_id;

    UPDATE public.alpha_agents
    SET metadata = jsonb_set(
            jsonb_set(
                jsonb_set(
                    jsonb_set(
                        metadata,
                        '{last_event_at}',
                        to_jsonb(NOW()::text),
                        true
                    ),
                    '{last_event_type}',
                    to_jsonb(p_event_type),
                    true
                ),
                '{last_event_severity}',
                to_jsonb(p_severity),
                true
            ),
            '{last_event_id}',
            to_jsonb(v_id::text),
            true
        ),
        updated_at = NOW()
    WHERE agent_id = p_agent_id;

    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_agent_event_notification(
    p_event_id UUID,
    p_status TEXT,
    p_result JSONB DEFAULT '{}'::jsonb,
    p_error TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);

    UPDATE public.alpha_agent_events
    SET notification_status = p_status,
        notification_result = COALESCE(p_result, '{}'::jsonb),
        notification_error = p_error,
        notified_at = CASE
            WHEN p_status IN ('sent', 'fallback_sent', 'failed', 'denied', 'skipped')
                THEN NOW()
            ELSE notified_at
        END
    WHERE id = p_event_id;
END;
$$;

GRANT EXECUTE ON FUNCTION public.record_agent_event(
    TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, UUID, TEXT, TEXT, TEXT
) TO jarvis_alpha_app, jarvis_alpha_writer;

GRANT EXECUTE ON FUNCTION public.mark_agent_event_notification(
    UUID, TEXT, JSONB, TEXT
) TO jarvis_alpha_app, jarvis_alpha_writer;

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('chatops.command_read', 'chatops', 'command_read',
     'Handle token-authenticated read-only Mattermost slash commands.', 'T1',
     'chatops.read', 'active', FALSE, FALSE, FALSE,
     '{"surface": "mattermost", "write_commands": "blocked"}'::jsonb)
ON CONFLICT (skill_name) DO UPDATE
SET description = EXCLUDED.description,
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
    ('approval_triage', 'Approval Triage',
     'Surface approval queue events and operator decisions into ChatOps.',
     'T2', 'active', TRUE, 'event_driven', NULL,
     ARRAY['notify.send', 'notify.send_mattermost', 'notify.send_pushover'],
     ARRAY['notify.send', 'approval.read'], 0.0,
     '{"writes": "blocked"}'::jsonb, '{}'::jsonb,
     '{"mattermost_channel_key": "needs_input"}'::jsonb),
    ('watchdog', 'Watchdog',
     'Surface infrastructure health degradation and restoration events.',
     'T2', 'active', TRUE, '60s', 'com.jarvis.alpha.watchdog',
     ARRAY['notify.send', 'notify.send_mattermost', 'notify.send_pushover'],
     ARRAY['notify.send', 'watchdog.events.ingest'], 0.0,
     '{"writes": "blocked"}'::jsonb, '{}'::jsonb,
     '{"mattermost_channel_key": "alerts"}'::jsonb)
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
    metadata = alpha_agents.metadata || EXCLUDED.metadata,
    updated_at = NOW();

UPDATE public.alpha_agents
SET allowed_skills = (
        SELECT ARRAY(
            SELECT DISTINCT skill
            FROM unnest(allowed_skills || ARRAY['notify.send']) AS skill
            ORDER BY skill
        )
    ),
    allowed_scopes = (
        SELECT ARRAY(
            SELECT DISTINCT scope
            FROM unnest(allowed_scopes || ARRAY['notify.send']) AS scope
            ORDER BY scope
        )
    ),
    metadata = metadata || '{"mattermost_channel_key": "alpha_events"}'::jsonb,
    updated_at = NOW()
WHERE agent_id IN ('dream_mode', 'network_watchdog', 'inbox_watcher', 'family_concierge');

UPDATE public.alpha_agents
SET metadata = metadata || '{"mattermost_channel_key": "alpha_events"}'::jsonb,
    updated_at = NOW()
WHERE agent_id = 'buddy';

DO $$
DECLARE
    v_missing integer;
BEGIN
    SELECT COUNT(*) INTO v_missing
    FROM public.alpha_agents
    WHERE agent_id IN ('buddy', 'dream_mode', 'approval_triage', 'watchdog')
      AND NOT ('notify.send' = ANY(allowed_skills))
      AND agent_id <> 'buddy';

    IF v_missing <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT agent notify allowlist FAILED: missing=%', v_missing;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE proname = 'record_agent_event'
          AND pronamespace = 'public'::regnamespace
          AND pg_get_functiondef(oid) LIKE '%set_config(''rls.role'', ''platform_admin'', true)%'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT record_agent_event SECDEF FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT agent ChatOps event contract OK';
END $$;
