-- Migration: 20260618_153000_obsidian_private_digest_skill
-- Purpose:   Add an explicit Obsidian private digest write skill for
--            privacy-safe document recall artifacts.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    (
     'notes.write_private_digest',
     'notes',
     'write_private_digest',
     'Write an idempotent private digest note into the Obsidian vault.',
     'T2',
     'notes.write',
     'active',
     TRUE,
     FALSE,
     TRUE,
     jsonb_build_object(
       'manifest',
       jsonb_build_object(
         'manifest_version', 1,
         'data_classification', 'personal',
         'side_effect_class', 'write',
         'input_schema_ref', 'registry://schemas/skill-input/default-v1',
         'output_schema_ref', 'registry://schemas/skill-output/default-v1',
         'runtime',
           jsonb_build_object(
             'timeout_s', 10,
             'retry_policy', 'idempotent_retry_once',
             'rate_limit', '30/minute/operator'
           ),
         'cost',
           jsonb_build_object(
             'mode', 'none',
             'max_usd_per_call', 0,
             'model_policy', NULL
           ),
         'egress',
           jsonb_build_object(
             'mode', 'local',
             'provider', 'obsidian',
             'allowed_hosts', '[]'::jsonb
           ),
         'audit',
           jsonb_build_object(
             'event_name', 'skill.invoke',
             'redact_fields', jsonb_build_array('token', 'secret', 'body')
           ),
         'compensation', 'delete_created_digest_note',
         'test_ref', 'tests/test_obsidian_skills.py',
         'runbook_ref', 'docs/JARVIS_Alpha_Skills_Agents_Catalog_v0_9.md'
       ),
       'execution_path', 'skill_runner',
       'config_secret', 'OBSIDIAN_VAULT_PATH',
       'default_path', 'AT-0/Private Document Digests'
     )
    )
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

UPDATE public.alpha_agents
   SET allowed_skills = (
           SELECT ARRAY(
               SELECT DISTINCT skill_name
                 FROM unnest(
                     allowed_skills
                     || ARRAY['notes.write_private_digest']::TEXT[]
                 ) AS skill_name
                ORDER BY skill_name
           )
       ),
       allowed_scopes = (
           SELECT ARRAY(
               SELECT DISTINCT scope_name
                 FROM unnest(
                     allowed_scopes || ARRAY['notes.write']::TEXT[]
                 ) AS scope_name
                ORDER BY scope_name
           )
       ),
       updated_at = NOW()
 WHERE agent_id = 'dream_mode';

DO $$
DECLARE
    v_skill_count INTEGER;
    v_missing_scope_count INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO v_skill_count
      FROM public.alpha_skill_registry
     WHERE skill_name = 'notes.write_private_digest'
       AND status = 'active'
       AND approval_tier = 'T2'
       AND scope = 'notes.write'
       AND mutates_state IS TRUE
       AND idempotency_required IS TRUE
       AND metadata->>'execution_path' = 'skill_runner'
       AND metadata->>'config_secret' = 'OBSIDIAN_VAULT_PATH'
       AND metadata->'manifest'->>'side_effect_class' = 'write';

    IF v_skill_count <> 1 THEN
        RAISE EXCEPTION 'POST-FLIGHT Obsidian private digest skill FAILED: count=%', v_skill_count;
    END IF;

    SELECT COUNT(*)
      INTO v_missing_scope_count
      FROM (VALUES ('notes.write')) AS required(scope_name)
     WHERE NOT EXISTS (
           SELECT 1
             FROM public.alpha_agents a
            WHERE a.agent_id = 'dream_mode'
              AND required.scope_name = ANY(a.allowed_scopes)
       );

    IF v_missing_scope_count <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Dream Mode notes.write scope FAILED: missing=%', v_missing_scope_count;
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.alpha_agents a
         WHERE a.agent_id = 'dream_mode'
           AND 'notes.write_private_digest' = ANY(a.allowed_skills)
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT Dream Mode private digest skill missing';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Obsidian private digest skill OK';
END $$;
