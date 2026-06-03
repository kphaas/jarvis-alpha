-- Migration: 20260603_163000_porchlight_scheduled_boundary
-- Purpose: Run Porchlight on schedule and document the external access boundary it checks.

UPDATE public.alpha_agents
SET cadence = 'daily',
    metadata = metadata || '{
      "schedule_interval_seconds": 86400,
      "external_boundary": {
        "protected_hosts_source": "PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS",
        "policy_emails_source": "PORCHLIGHT_CLOUDFLARE_EXPECTED_POLICY_EMAILS",
        "forbidden_apps": ["alpha", "brain", "jarvis-brain"],
        "broad_rules_blocked": ["everyone", "email_domain", "bypass"]
      }
    }'::jsonb,
    updated_at = NOW()
WHERE agent_id = 'porchlight';

DO $$
DECLARE
    v_interval integer;
    v_boundary jsonb;
BEGIN
    SELECT (metadata->>'schedule_interval_seconds')::integer,
           metadata->'external_boundary'
      INTO v_interval, v_boundary
    FROM public.alpha_agents
    WHERE agent_id = 'porchlight';

    IF v_interval IS DISTINCT FROM 86400
       OR v_boundary->>'protected_hosts_source' IS DISTINCT FROM 'PORCHLIGHT_CLOUDFLARE_EXPECTED_HOSTS'
       OR NOT (v_boundary->'broad_rules_blocked' ? 'bypass') THEN
        RAISE EXCEPTION 'POST-FLIGHT Porchlight scheduled boundary metadata FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Porchlight scheduled boundary metadata OK';
END $$;
