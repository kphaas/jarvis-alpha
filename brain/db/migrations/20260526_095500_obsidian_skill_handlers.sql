-- Migration: 20260526_095500_obsidian_skill_handlers
-- Purpose:   Activate governed Obsidian note/task skills and allow Dream Mode
--            to invoke them through SkillRunner/SkillPolicyGate.

UPDATE public.alpha_skill_registry
   SET status = 'active',
       metadata = metadata
           || jsonb_build_object(
               'execution_path', 'skill_runner',
               'config_secret', 'OBSIDIAN_VAULT_PATH'
           ),
       updated_at = NOW()
 WHERE skill_name = 'notes.search';

UPDATE public.alpha_skill_registry
   SET status = 'active',
       metadata = metadata
           || jsonb_build_object(
               'execution_path', 'skill_runner',
               'config_secret', 'OBSIDIAN_VAULT_PATH',
               'default_path_secret', 'OBSIDIAN_TASKS_INBOX'
           ),
       updated_at = NOW()
 WHERE skill_name = 'tasks.create';

UPDATE public.alpha_skill_registry
   SET metadata = metadata
           || jsonb_build_object(
               'execution_path', 'fastapi_route'
           ),
       updated_at = NOW()
 WHERE skill_name = 'chatops.command_read';

UPDATE public.alpha_agents
   SET allowed_scopes = (
           SELECT ARRAY(
               SELECT DISTINCT scope_name
                 FROM unnest(
                     allowed_scopes || ARRAY['notes.read', 'tasks.write']::TEXT[]
                 ) AS scope_name
                ORDER BY scope_name
           )
       ),
       updated_at = NOW()
 WHERE agent_id = 'dream_mode';

DO $$
DECLARE
    v_active_count INTEGER;
    v_missing_scope_count INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO v_active_count
      FROM public.alpha_skill_registry
     WHERE skill_name IN ('notes.search', 'tasks.create')
       AND status = 'active'
       AND metadata->>'execution_path' = 'skill_runner'
       AND metadata->>'config_secret' = 'OBSIDIAN_VAULT_PATH';

    IF v_active_count <> 2 THEN
        RAISE EXCEPTION 'POST-FLIGHT Obsidian skill activation FAILED: active_count=%', v_active_count;
    END IF;

    SELECT COUNT(*)
      INTO v_missing_scope_count
      FROM (VALUES ('notes.read'), ('tasks.write')) AS required(scope_name)
     WHERE NOT EXISTS (
           SELECT 1
             FROM public.alpha_agents a
            WHERE a.agent_id = 'dream_mode'
              AND required.scope_name = ANY(a.allowed_scopes)
       );

    IF v_missing_scope_count <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Dream Mode Obsidian scopes FAILED: missing=%', v_missing_scope_count;
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

    RAISE NOTICE 'POST-FLIGHT Obsidian skill handlers OK';
END $$;
