-- Migration: 20260526_084500_skill_manifest_dream_ledger
-- Purpose:   Promote skill metadata to a typed Skill Manifest v1 contract and
--            mirror Dream sessions into the durable agent run ledger.

UPDATE public.alpha_skill_registry
SET metadata =
    jsonb_build_object(
        'manifest',
        jsonb_build_object(
            'manifest_version', 1,
            'data_classification',
                CASE
                    WHEN body_access THEN 'message_body'
                    WHEN skill_name = 'gmail.draft_reply' THEN 'message_body'
                    WHEN skill_name = 'unifi.daughters_screentime' THEN 'child'
                    WHEN domain IN ('unifi') THEN 'security'
                    WHEN scope LIKE 'smarthome.security%' THEN 'security'
                    WHEN domain IN ('gmail', 'imessage', 'smarthome', 'tasks', 'notes') THEN 'personal'
                    WHEN domain IN ('notify', 'chatops') THEN 'ops'
                    ELSE 'none'
                END,
            'side_effect_class',
                CASE
                    WHEN NOT mutates_state THEN 'read'
                    WHEN domain = 'notify' THEN 'operator_notification'
                    WHEN domain IN ('gmail', 'imessage') AND action LIKE 'send%' THEN 'external_send'
                    WHEN domain = 'smarthome' THEN 'physical_world'
                    WHEN skill_name = 'unifi.daughters_screentime' THEN 'physical_world'
                    ELSE 'write'
                END,
            'input_schema_ref', 'registry://schemas/skill-input/default-v1',
            'output_schema_ref', 'registry://schemas/skill-output/default-v1',
            'runtime',
                jsonb_build_object(
                    'timeout_s',
                        CASE
                            WHEN domain IN ('notify', 'chatops', 'tasks', 'notes') THEN 10
                            WHEN domain = 'smarthome' THEN 15
                            ELSE 20
                        END,
                    'retry_policy',
                        CASE
                            WHEN mutates_state THEN 'idempotent_retry_once'
                            WHEN domain IN ('gmail', 'imessage') THEN 'transient_retry'
                            ELSE 'none'
                        END,
                    'rate_limit',
                        CASE
                            WHEN domain = 'notify' THEN '60/minute/system'
                            WHEN domain = 'chatops' THEN '30/minute/operator'
                            WHEN domain = 'unifi' THEN '30/minute/agent'
                            WHEN domain IN ('gmail', 'imessage') AND action LIKE 'send%' THEN '10/hour/operator'
                            WHEN domain IN ('gmail', 'imessage') THEN '60/minute/account'
                            WHEN domain = 'smarthome' THEN '10/hour/home'
                            WHEN domain IN ('tasks', 'notes') THEN '60/minute/operator'
                            ELSE 'default'
                        END
                ),
            'cost',
                jsonb_build_object(
                    'mode', 'none',
                    'max_usd_per_call', 0,
                    'model_policy', NULL
                ),
            'egress',
                jsonb_build_object(
                    'mode',
                        CASE
                            WHEN domain IN ('notify', 'unifi', 'gmail') THEN 'gateway'
                            WHEN domain IN ('imessage', 'smarthome') THEN 'tailscale'
                            WHEN domain IN ('tasks', 'notes', 'chatops') THEN 'local'
                            ELSE 'none'
                        END,
                    'provider',
                        CASE
                            WHEN skill_name = 'notify.send_pushover' THEN 'pushover'
                            WHEN domain = 'notify' THEN 'mattermost'
                            WHEN domain = 'unifi' THEN 'unifi'
                            WHEN domain = 'gmail' THEN 'gmail'
                            WHEN domain = 'imessage' THEN 'bluebubbles'
                            WHEN domain = 'smarthome' THEN 'home_assistant'
                            WHEN domain = 'tasks' THEN 'obsidian_tasks'
                            WHEN domain = 'notes' THEN 'obsidian'
                            WHEN domain = 'chatops' THEN 'mattermost'
                            ELSE NULL
                        END,
                    'allowed_hosts', '[]'::jsonb
                ),
            'audit',
                jsonb_build_object(
                    'event_name', 'skill.invoke',
                    'redact_fields', jsonb_build_array('token', 'secret', 'body')
                ),
            'compensation',
                CASE
                    WHEN domain = 'notify' THEN 'send_followup_correction'
                    WHEN domain IN ('gmail', 'imessage') AND action LIKE 'send%' THEN 'send_correction_or_followup'
                    WHEN skill_name = 'gmail.draft_reply' THEN 'delete_or_replace_draft'
                    WHEN domain = 'smarthome' THEN 'restore_previous_home_state'
                    WHEN skill_name = 'unifi.daughters_screentime' THEN 'restore_previous_network_state'
                    WHEN skill_name = 'tasks.create' THEN 'delete_or_mark_created_task_cancelled'
                    ELSE 'not_applicable'
                END,
            'test_ref',
                CASE
                    WHEN domain = 'notify' THEN 'tests/test_notify_skill.py'
                    WHEN domain = 'chatops' THEN 'tests/test_agent_events_chatops.py'
                    WHEN domain = 'unifi' THEN 'tests/test_agent_runtime_network.py'
                    WHEN domain IN ('gmail', 'imessage', 'smarthome') THEN 'tests/test_skill_policy_gate.py'
                    ELSE 'tests/test_agent_skill_registry.py'
                END,
            'runbook_ref', 'docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md'
        )
    )
    || (metadata - 'manifest'),
    updated_at = NOW();

ALTER TABLE public.alpha_skill_registry
DROP CONSTRAINT IF EXISTS alpha_skill_registry_manifest_v1_check;

ALTER TABLE public.alpha_skill_registry
ADD CONSTRAINT alpha_skill_registry_manifest_v1_check
CHECK (
    jsonb_typeof(metadata->'manifest') = 'object'
    AND metadata->'manifest'->>'manifest_version' = '1'
    AND metadata->'manifest'->>'data_classification' IN (
        'none', 'ops', 'personal', 'message_body', 'child',
        'financial', 'medical', 'security'
    )
    AND metadata->'manifest'->>'side_effect_class' IN (
        'read', 'write', 'external_send', 'physical_world',
        'operator_notification', 'control_plane'
    )
    AND metadata->'manifest' ?& ARRAY[
        'input_schema_ref', 'output_schema_ref', 'runtime', 'cost',
        'egress', 'audit', 'compensation', 'test_ref', 'runbook_ref'
    ]
    AND jsonb_typeof(metadata->'manifest'->'runtime') = 'object'
    AND jsonb_typeof(metadata->'manifest'->'cost') = 'object'
    AND jsonb_typeof(metadata->'manifest'->'egress') = 'object'
    AND jsonb_typeof(metadata->'manifest'->'audit') = 'object'
    AND metadata->'manifest'->'runtime' ?& ARRAY['timeout_s', 'retry_policy', 'rate_limit']
    AND metadata->'manifest'->'cost' ?& ARRAY['mode', 'max_usd_per_call', 'model_policy']
    AND metadata->'manifest'->'egress' ?& ARRAY['mode', 'provider', 'allowed_hosts']
    AND metadata->'manifest'->'audit' ?& ARRAY['event_name', 'redact_fields']
);

CREATE INDEX IF NOT EXISTS idx_alpha_skill_registry_manifest_class
    ON public.alpha_skill_registry ((metadata->'manifest'->>'data_classification'));

CREATE INDEX IF NOT EXISTS idx_alpha_skill_registry_manifest_effect
    ON public.alpha_skill_registry ((metadata->'manifest'->>'side_effect_class'));

CREATE INDEX IF NOT EXISTS idx_alpha_agent_runs_dream_session
    ON public.alpha_agent_runs ((metadata->>'dream_session_id'))
    WHERE agent_id = 'dream_mode' AND metadata ? 'dream_session_id';

CREATE OR REPLACE FUNCTION public.upsert_dream_agent_run(p_session_id BIGINT)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_session public.alpha_dream_sessions%ROWTYPE;
    v_run_id UUID;
    v_run_status TEXT;
    v_error_text TEXT;
    v_metadata JSONB;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);

    SELECT *
      INTO v_session
      FROM public.alpha_dream_sessions
     WHERE id = p_session_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'dream session not found: %', p_session_id;
    END IF;

    v_run_status := CASE v_session.status
        WHEN 'completed' THEN 'succeeded'
        WHEN 'failed' THEN 'failed'
        WHEN 'killed' THEN 'cancelled'
        WHEN 'halted' THEN 'cancelled'
        WHEN 'aborted' THEN 'cancelled'
        WHEN 'running' THEN 'running'
        ELSE 'queued'
    END;

    v_error_text := CASE
        WHEN v_run_status IN ('failed', 'cancelled')
        THEN NULLIF(COALESCE(v_session.kill_reason, v_session.summary), '')
        ELSE NULL
    END;

    v_metadata := jsonb_strip_nulls(jsonb_build_object(
        'source', 'dream_session',
        'dream_session_id', v_session.id::text,
        'dream_status', v_session.status,
        'trigger', v_session.trigger,
        'workflow_id', v_session.temporal_workflow_id,
        'workflow_run_id', v_session.temporal_run_id,
        'goal_type', v_session.goal_type,
        'goal_preview', LEFT(COALESCE(v_session.goal_text, ''), 240),
        'review_verdict', v_session.review_verdict,
        'step_count', v_session.step_count,
        'steps_completed', v_session.steps_completed,
        'steps_failed', v_session.steps_failed,
        'steps_blocked', v_session.steps_blocked,
        'briefing_published', EXISTS (
            SELECT 1
             FROM public.alpha_briefings b
             WHERE b.source = 'dream_mode'
               AND b.markdown LIKE '%Session ' || v_session.id::text || '%'
        )
    ));

    SELECT id
      INTO v_run_id
      FROM public.alpha_agent_runs
     WHERE agent_id = 'dream_mode'
       AND metadata->>'dream_session_id' = v_session.id::text
     ORDER BY created_at DESC
     LIMIT 1;

    IF v_run_id IS NULL THEN
        INSERT INTO public.alpha_agent_runs (
            agent_id,
            status,
            trigger_type,
            trace_id,
            started_at,
            completed_at,
            cost_usd,
            error_text,
            metadata
        )
        VALUES (
            'dream_mode',
            v_run_status,
            COALESCE(v_session.trigger, 'manual'),
            v_session.temporal_workflow_id,
            COALESCE(v_session.started_at, v_session.created_at),
            CASE
                WHEN v_run_status IN ('succeeded', 'failed', 'cancelled')
                THEN v_session.finished_at
                ELSE NULL
            END,
            COALESCE(v_session.cost_actual_usd, 0),
            v_error_text,
            v_metadata
        )
        RETURNING id INTO v_run_id;
    ELSE
        UPDATE public.alpha_agent_runs
           SET status = v_run_status,
               trigger_type = COALESCE(v_session.trigger, trigger_type),
               trace_id = COALESCE(v_session.temporal_workflow_id, trace_id),
               started_at = COALESCE(v_session.started_at, started_at, v_session.created_at),
               completed_at = CASE
                   WHEN v_run_status IN ('succeeded', 'failed', 'cancelled')
                   THEN v_session.finished_at
                   ELSE completed_at
               END,
               cost_usd = COALESCE(v_session.cost_actual_usd, 0),
               error_text = v_error_text,
               metadata = metadata || v_metadata
         WHERE id = v_run_id;
    END IF;

    UPDATE public.alpha_agents
       SET metadata = jsonb_set(
               jsonb_set(metadata, '{last_run_status}', to_jsonb(v_run_status), true),
               '{last_dream_session_id}', to_jsonb(v_session.id::text), true
           ),
           updated_at = NOW()
     WHERE agent_id = 'dream_mode';

    RETURN v_run_id;
END;
$$;

GRANT EXECUTE ON FUNCTION public.upsert_dream_agent_run(BIGINT)
TO jarvis_alpha_app, jarvis_alpha_writer;

SELECT public.upsert_dream_agent_run(id)
  FROM (
      SELECT id
        FROM public.alpha_dream_sessions
       WHERE status IN ('completed', 'failed', 'halted', 'killed', 'aborted', 'running')
         AND (
             temporal_workflow_id IS NOT NULL
             OR status IN ('completed', 'failed', 'halted', 'killed', 'aborted')
         )
       ORDER BY COALESCE(finished_at, started_at, created_at) ASC, id ASC
  ) eligible_dream_sessions;

DO $$
DECLARE
    v_missing_manifest INTEGER;
    v_eligible_dream_sessions INTEGER;
    v_dream_runs INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO v_missing_manifest
      FROM public.alpha_skill_registry
     WHERE NOT (metadata ? 'manifest')
        OR metadata->'manifest'->>'manifest_version' <> '1';

    IF v_missing_manifest <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Skill Manifest v1 FAILED: missing=%', v_missing_manifest;
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'alpha_skill_registry_manifest_v1_check'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT Skill Manifest v1 FAILED: constraint missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_proc
         WHERE proname = 'upsert_dream_agent_run'
           AND pronamespace = 'public'::regnamespace
           AND pg_get_functiondef(oid) LIKE '%set_config(''rls.role'', ''platform_admin'', true)%'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT Dream ledger bridge SECDEF FAILED';
    END IF;

    SELECT COUNT(*)
      INTO v_eligible_dream_sessions
      FROM public.alpha_dream_sessions
     WHERE status IN ('completed', 'failed', 'halted', 'killed', 'aborted', 'running')
       AND (
           temporal_workflow_id IS NOT NULL
           OR status IN ('completed', 'failed', 'halted', 'killed', 'aborted')
       );

    SELECT COUNT(*)
      INTO v_dream_runs
      FROM public.alpha_agent_runs
     WHERE agent_id = 'dream_mode'
       AND metadata ? 'dream_session_id';

    IF v_eligible_dream_sessions > 0 AND v_dream_runs = 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Dream ledger bridge FAILED: no mirrored runs';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Skill Manifest v1 + Dream ledger OK: eligible_dream_sessions=%, dream_runs=%',
        v_eligible_dream_sessions,
        v_dream_runs;
END $$;
