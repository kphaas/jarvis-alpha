-- Migration: 20260526_113500_skillrunner_approval_canary
-- Purpose:   Seed a harmless T4 SkillRunner canary so approval queue bridge
--            replay can be tested before enabling real high-risk skills.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    (
        'approval.canary_t4',
        'approval',
        'canary_t4',
        'No-op T4 canary for proving SkillRunner approval queue replay.',
        'T4',
        'approval.canary',
        'active',
        TRUE,
        FALSE,
        TRUE,
        jsonb_build_object(
            'execution_path', 'skill_runner',
            'approval_queue_bridge', 'enabled',
            'canary', TRUE,
            'manifest', jsonb_build_object(
                'manifest_version', 1,
                'data_classification', 'ops',
                'side_effect_class', 'control_plane',
                'input_schema_ref', 'registry://schemas/skill-input/default-v1',
                'output_schema_ref', 'registry://schemas/skill-output/default-v1',
                'runtime', jsonb_build_object(
                    'timeout_s', 5,
                    'retry_policy', 'idempotent_retry_once',
                    'rate_limit', '5/day/operator'
                ),
                'cost', jsonb_build_object(
                    'mode', 'none',
                    'max_usd_per_call', 0,
                    'model_policy', NULL
                ),
                'egress', jsonb_build_object(
                    'mode', 'none',
                    'provider', NULL,
                    'allowed_hosts', '[]'::jsonb
                ),
                'audit', jsonb_build_object(
                    'event_name', 'skill.invoke',
                    'redact_fields', jsonb_build_array('token', 'secret', 'body')
                ),
                'compensation', 'not_applicable_no_external_side_effect',
                'test_ref', 'tests/test_approval_canary_skill.py',
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

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    (
        'approval_canary',
        'Approval Canary',
        'Disabled no-op agent used only to prove SkillRunner T4 approval queue replay.',
        'T4',
        'active',
        FALSE,
        'manual_test_only',
        NULL,
        ARRAY['approval.canary_t4'],
        ARRAY['approval.canary'],
        0.0,
        '{"writes": "approval_queue", "external_side_effects": "blocked"}'::jsonb,
        '{}'::jsonb,
        '{"mattermost_channel_key": "needs_input", "manual_run_enabled": false, "canary": true}'::jsonb
    )
ON CONFLICT (agent_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    purpose = EXCLUDED.purpose,
    risk_tier = EXCLUDED.risk_tier,
    status = EXCLUDED.status,
    enabled = FALSE,
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
        FROM public.alpha_skill_registry
        WHERE skill_name = 'approval.canary_t4'
          AND status = 'active'
          AND approval_tier = 'T4'
          AND mutates_state = TRUE
          AND idempotency_required = TRUE
          AND metadata->>'execution_path' = 'skill_runner'
          AND metadata->>'approval_queue_bridge' = 'enabled'
          AND metadata->'manifest'->>'side_effect_class' = 'control_plane'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT approval.canary_t4 seed FAILED';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.alpha_agents
        WHERE agent_id = 'approval_canary'
          AND status = 'active'
          AND enabled = FALSE
          AND ARRAY['approval.canary_t4']::TEXT[] <@ allowed_skills
          AND ARRAY['approval.canary']::TEXT[] <@ allowed_scopes
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT approval_canary disabled posture FAILED';
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

    RAISE NOTICE 'POST-FLIGHT SkillRunner approval canary OK';
END $$;

