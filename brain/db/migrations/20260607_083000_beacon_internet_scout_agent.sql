-- Migration: 20260607_083000_beacon_internet_scout_agent
-- Purpose:   Register Beacon Internet Scout as a managed Alpha agent.
--            Chat uses only search/deep-research evidence paths; browser
--            remains exact approval-gated.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('internet_scout.search', 'internet_scout', 'search',
     'Gather public search evidence through Beacon and Gateway without browser automation.',
     'T2', 'internet_scout.research', 'active', FALSE, TRUE, FALSE,
     jsonb_build_object(
       'owner_agent', 'internet_scout',
       'chat_mode', 'web_search',
       'execution_path', 'fastapi_route',
       'manifest', jsonb_build_object(
         'manifest_version', 1,
         'data_classification', 'message_body',
         'side_effect_class', 'read',
         'input_schema_ref', 'registry://schemas/skill-input/default-v1',
         'output_schema_ref', 'registry://schemas/skill-output/default-v1',
         'runtime', jsonb_build_object(
           'timeout_s', 45,
           'retry_policy', 'gateway_provider_fallback',
           'rate_limit', '60/hour/user'
         ),
         'cost', jsonb_build_object(
           'mode', 'cloud',
           'max_usd_per_call', 0.02,
           'model_policy', 'gateway_search_provider_order'
         ),
         'egress', jsonb_build_object(
           'mode', 'gateway',
           'provider', 'beacon',
           'allowed_hosts', '[]'::jsonb
         ),
         'audit', jsonb_build_object(
           'event_name', 'skill.invoke',
           'redact_fields', '["token", "secret", "body", "query"]'::jsonb
         ),
         'compensation', 'not_applicable',
         'test_ref', 'tests/test_internet_scout_chat_adapter.py',
         'runbook_ref', 'docs/adr/ADR-0019-beacon-internet-scout.md'
       )
     )),
    ('internet_scout.deep_research', 'internet_scout', 'deep_research',
     'Gather higher-scrutiny cited web evidence through Beacon for chat research mode.',
     'T3', 'internet_scout.research', 'active', FALSE, TRUE, FALSE,
     jsonb_build_object(
       'owner_agent', 'internet_scout',
       'chat_mode', 'deep_research',
       'browser_use', 'approval_queue_only',
       'execution_path', 'fastapi_route',
       'manifest', jsonb_build_object(
         'manifest_version', 1,
         'data_classification', 'message_body',
         'side_effect_class', 'read',
         'input_schema_ref', 'registry://schemas/skill-input/default-v1',
         'output_schema_ref', 'registry://schemas/skill-output/default-v1',
         'runtime', jsonb_build_object(
           'timeout_s', 90,
           'retry_policy', 'gateway_provider_fallback',
           'rate_limit', '20/hour/user'
         ),
         'cost', jsonb_build_object(
           'mode', 'cloud',
           'max_usd_per_call', 0.10,
           'model_policy', 'gateway_search_provider_order'
         ),
         'egress', jsonb_build_object(
           'mode', 'gateway',
           'provider', 'beacon',
           'allowed_hosts', '[]'::jsonb
         ),
         'audit', jsonb_build_object(
           'event_name', 'skill.invoke',
           'redact_fields', '["token", "secret", "body", "query"]'::jsonb
         ),
         'compensation', 'not_applicable',
         'test_ref', 'tests/test_internet_scout_chat_adapter.py',
         'runbook_ref', 'docs/adr/ADR-0019-beacon-internet-scout.md'
       )
     )),
    ('internet_scout.browser_task', 'internet_scout', 'browser_task',
     'Queue or run exact-match approved Beacon browser tasks through the approval gate.',
     'T4', 'internet_scout.browser', 'active', TRUE, TRUE, TRUE,
     jsonb_build_object(
       'owner_agent', 'internet_scout',
       'approval_required', true,
       'browser_use', 'exact_approval_hash_required',
       'execution_path', 'fastapi_route',
       'manifest', jsonb_build_object(
         'manifest_version', 1,
         'data_classification', 'message_body',
         'side_effect_class', 'control_plane',
         'input_schema_ref', 'registry://schemas/skill-input/default-v1',
         'output_schema_ref', 'registry://schemas/skill-output/default-v1',
         'runtime', jsonb_build_object(
           'timeout_s', 120,
           'retry_policy', 'approval_idempotency_key',
           'rate_limit', '10/hour/user'
         ),
         'cost', jsonb_build_object(
           'mode', 'cloud',
           'max_usd_per_call', 0.20,
           'model_policy', 'no_autonomous_browser_use'
         ),
         'egress', jsonb_build_object(
           'mode', 'gateway',
           'provider', 'beacon_browser_runtime',
           'allowed_hosts', '[]'::jsonb
         ),
         'audit', jsonb_build_object(
           'event_name', 'skill.invoke',
           'redact_fields', '["token", "secret", "body", "query"]'::jsonb
         ),
         'compensation', 'expire_or_cancel_unconsumed_approval',
         'test_ref', 'tests/test_internet_scout_route.py',
         'runbook_ref', 'docs/adr/ADR-0019-beacon-internet-scout.md'
       )
     ))
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
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

INSERT INTO public.alpha_agents
    (agent_id, display_name, purpose, risk_tier, status, enabled, cadence,
     launch_label, allowed_skills, allowed_scopes, cost_daily_cap_usd,
     approval_policy, model_policy, metadata)
VALUES
    ('internet_scout', 'Beacon Internet Scout',
     'Broker current public internet evidence for Alpha chat and approved JARVIS consumers without letting web content issue instructions.',
     'T4', 'active', TRUE, 'on_demand', NULL,
     ARRAY[
       'internet_scout.search',
       'internet_scout.deep_research',
       'internet_scout.browser_task'
     ],
     ARRAY[
       'internet_scout.read',
       'internet_scout.research',
       'internet_scout.consumer',
       'internet_scout.browser',
       'approval.request'
     ],
     1.0,
     '{
        "search": "T2_no_browser",
        "deep_research": "T3_cited_evidence_only",
        "browser_use": "T4_exact_approval_required",
        "memory_promotion": "review_required",
        "raw_web_content": "untrusted_data_only"
      }'::jsonb,
     '{}'::jsonb,
     '{
        "mattermost_channel_key": "alpha_events",
        "manual_run_enabled": true,
        "operator_surfaces": ["health_panel", "helm_ask"],
        "evidence_store": "alpha_internet_requests",
        "gateway_owned_egress": true,
        "chat_modes": ["web_search", "deep_research"],
        "browser_runtime": "approval_queue_only",
        "prompt_injection_boundary": "web_content_is_data_not_commands"
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
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

DO $$
DECLARE
    v_agent record;
    v_skill_count integer;
BEGIN
    SELECT * INTO v_agent
    FROM public.alpha_agents
    WHERE agent_id = 'internet_scout';

    SELECT COUNT(*) INTO v_skill_count
    FROM public.alpha_skill_registry
    WHERE skill_name IN (
      'internet_scout.search',
      'internet_scout.deep_research',
      'internet_scout.browser_task'
    );

    IF v_agent IS NULL
       OR v_agent.risk_tier != 'T4'
       OR NOT v_agent.enabled
       OR v_skill_count != 3
       OR NOT ('internet_scout.search' = ANY(v_agent.allowed_skills))
       OR NOT ('internet_scout.deep_research' = ANY(v_agent.allowed_skills))
       OR NOT ('internet_scout.browser_task' = ANY(v_agent.allowed_skills))
       OR v_agent.approval_policy->>'raw_web_content' != 'untrusted_data_only' THEN
        RAISE EXCEPTION 'POST-FLIGHT beacon internet scout agent registration FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT beacon internet scout agent registration OK';
END $$;
