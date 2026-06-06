-- Migration: 20260606_145000_beacon_secdef_owner_containment
-- Purpose: keep Beacon SECURITY DEFINER ownership inside the Alpha owner role.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'jarvis_alpha_owner'
    ) THEN
        EXECUTE
            'ALTER FUNCTION public.save_beacon_semantic_memory'
            || '(uuid, text, text, text, text) OWNER TO jarvis_alpha_owner';
    END IF;
END
$$;

DO $$
DECLARE
    v_owner text;
BEGIN
    SELECT pg_get_userbyid(p.proowner)
      INTO v_owner
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
       AND p.proname = 'save_beacon_semantic_memory'
       AND pg_get_function_identity_arguments(p.oid) =
           'p_user_id uuid, p_fact text, p_category text, p_source_url text, p_source_content_hash text';

    IF v_owner IS DISTINCT FROM 'jarvis_alpha_owner' THEN
        RAISE EXCEPTION 'POST-FLIGHT Beacon SECURITY DEFINER owner FAILED: %', v_owner;
    END IF;

    RAISE NOTICE 'POST-FLIGHT Beacon SECURITY DEFINER owner OK';
END
$$;
