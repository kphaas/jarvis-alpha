-- Migration: 20260526_164500_weather_current_skill
-- Purpose:   Activate governed weather.current read skill through Gateway.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    (
        'weather.current',
        'weather',
        'current',
        'Read current weather conditions through Gateway''s Open-Meteo adapter.',
        'T1',
        'weather.read',
        'active',
        FALSE,
        FALSE,
        FALSE,
        jsonb_build_object(
            'execution_path', 'skill_runner',
            'cache_ttl_seconds', 600,
            'location_policy', 'configured_home_or_explicit_coordinates',
            'manifest', jsonb_build_object(
                'manifest_version', 1,
                'data_classification', 'personal',
                'side_effect_class', 'read',
                'input_schema_ref', 'registry://schemas/skill-input/default-v1',
                'output_schema_ref', 'registry://schemas/skill-output/default-v1',
                'runtime', jsonb_build_object(
                    'timeout_s', 15,
                    'retry_policy', 'cache_then_transient_retry',
                    'rate_limit', '30/minute/system'
                ),
                'cost', jsonb_build_object(
                    'mode', 'none',
                    'max_usd_per_call', 0.0,
                    'model_policy', NULL
                ),
                'egress', jsonb_build_object(
                    'mode', 'gateway',
                    'provider', 'open_meteo',
                    'allowed_hosts', jsonb_build_array('api.open-meteo.com')
                ),
                'audit', jsonb_build_object(
                    'event_name', 'skill.invoke',
                    'redact_fields', jsonb_build_array('token', 'secret', 'body')
                ),
                'compensation', 'not_applicable',
                'test_ref', 'tests/test_weather_skill.py',
                'runbook_ref', 'docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md'
            )
        )
    )
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

UPDATE public.alpha_agents
   SET allowed_skills = (
           SELECT ARRAY(
               SELECT DISTINCT skill_name
                 FROM unnest(allowed_skills || ARRAY['weather.current']::TEXT[]) AS skill_name
                ORDER BY skill_name
           )
       ),
       allowed_scopes = (
           SELECT ARRAY(
               SELECT DISTINCT scope_name
                 FROM unnest(allowed_scopes || ARRAY['weather.read']::TEXT[]) AS scope_name
                ORDER BY scope_name
           )
       ),
       updated_at = NOW()
 WHERE agent_id = 'family_concierge';

DO $$
DECLARE
    v_skill_count INTEGER;
    v_family_policy_ok BOOLEAN;
BEGIN
    SELECT COUNT(*)
      INTO v_skill_count
      FROM public.alpha_skill_registry
     WHERE skill_name = 'weather.current'
       AND status = 'active'
       AND approval_tier = 'T1'
       AND scope = 'weather.read'
       AND metadata->>'execution_path' = 'skill_runner'
       AND metadata->'manifest'->'egress'->>'provider' = 'open_meteo';

    IF v_skill_count <> 1 THEN
        RAISE EXCEPTION 'POST-FLIGHT weather.current skill FAILED: count=%', v_skill_count;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM public.alpha_agents
         WHERE agent_id = 'family_concierge'
           AND 'weather.current' = ANY(allowed_skills)
           AND 'weather.read' = ANY(allowed_scopes)
    )
      INTO v_family_policy_ok;

    IF NOT v_family_policy_ok THEN
        RAISE EXCEPTION 'POST-FLIGHT family_concierge weather policy FAILED';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM public.alpha_skill_registry
         WHERE status = 'active'
           AND approval_tier IN ('T4', 'T5')
           AND metadata->>'approval_queue_bridge' IS DISTINCT FROM 'enabled'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT active high-risk skills require approval bridge';
    END IF;

    RAISE NOTICE 'POST-FLIGHT weather.current skill OK';
END $$;
