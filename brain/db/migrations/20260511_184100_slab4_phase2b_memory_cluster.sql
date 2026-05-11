-- Migration: 20260511_184100_slab4_phase2b_memory_cluster
-- Purpose:   Slab 4 Phase 2b — close Class A SECDEF pattern hole in the memory cluster.
--            Add `PERFORM set_config('rls.role','platform_admin',true)` to the top of 11
--            SECURITY DEFINER functions that operate on FORCE-RLS tables
--            (alpha_conversation_memory, alpha_semantic_memory).
-- Reference: docs/discovery/DISCOVERY_2026-05-11_slab4_phase1a_secdef_audit.md (§5 HIGH)
-- Functions: store_conversation_memory, save_semantic_memory,
--            cap_episodic_memory, cap_semantic_memory,
--            evict_episodic_memory_older_than, evict_expired_working_memory,
--            forget_memory_by_topic, forget_working_memory,
--            bump_memory_access, get_buddy_promotion_candidates,
--            list_active_memory_users.
-- Body diff: One inserted line at top of each function body; existing logic unchanged.
-- Search-path note: each function preserves its existing SET search_path TO ... exactly
--                   (some use 'pg_catalog, public', others 'pg_catalog, public, pg_temp').
-- Verify:    Introspect (pg_get_functiondef LIKE) + functional smoke under
--            jarvis_alpha_writer in a SAVEPOINT that is rolled back.

-- -------------------------------------------------------------------------
-- 1. store_conversation_memory
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.store_conversation_memory(p_user_id text, p_session_id text, p_role text, p_summary text, p_embedding vector, p_tier text, p_persistent boolean, p_importance double precision)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  v_id UUID;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  INSERT INTO public.alpha_conversation_memory
    (user_id, session_id, role, content, summary, memory_type, embedding, tier, persistent, importance_score)
  VALUES
    (p_user_id, p_session_id, p_role, p_summary, p_summary, p_role, p_embedding, p_tier, p_persistent, p_importance)
  RETURNING id INTO v_id;

  RETURN v_id;
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'store_conversation_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN NULL;
END;
$function$;

-- -------------------------------------------------------------------------
-- 2. save_semantic_memory
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.save_semantic_memory(p_user_id uuid, p_fact text, p_category text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  v_inserted INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  INSERT INTO public.alpha_semantic_memory
    (user_id, fact, category, source)
  SELECT
    p_user_id, p_fact, p_category, 'explicit'
  WHERE (
    SELECT COUNT(*)
    FROM public.alpha_semantic_memory
    WHERE user_id = p_user_id
  ) < 50;

  GET DIAGNOSTICS v_inserted = ROW_COUNT;

  IF v_inserted = 0 THEN
    RETURN jsonb_build_object('saved', false, 'reason', 'cap_reached');
  END IF;

  RETURN jsonb_build_object(
    'saved', true,
    'fact', p_fact,
    'category', p_category
  );
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'save_semantic_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN jsonb_build_object('saved', false, 'reason', 'error');
END;
$function$;

-- -------------------------------------------------------------------------
-- 3. cap_episodic_memory
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.cap_episodic_memory(p_user_id text, p_max_rows integer)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
  v_count INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  IF p_user_id IS NULL OR p_user_id = '' THEN
    RAISE EXCEPTION 'cap_episodic_memory: p_user_id required' USING ERRCODE = '22023';
  END IF;

  DELETE FROM public.alpha_conversation_memory
  WHERE id IN (
    SELECT id FROM public.alpha_conversation_memory
    WHERE tier = 'episodic' AND user_id = p_user_id
    ORDER BY created_at DESC
    OFFSET p_max_rows
  );

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' OR sqlstate '23P01' THEN
    RAISE;
  WHEN sqlstate '40001' OR sqlstate '40P01' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'cap_episodic_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$function$;

-- -------------------------------------------------------------------------
-- 4. cap_semantic_memory
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.cap_semantic_memory(p_user_id text, p_max_rows integer)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
  v_count INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  IF p_user_id IS NULL OR p_user_id = '' THEN
    RAISE EXCEPTION 'cap_semantic_memory: p_user_id required' USING ERRCODE = '22023';
  END IF;

  DELETE FROM public.alpha_conversation_memory
  WHERE id IN (
    SELECT id FROM public.alpha_conversation_memory
    WHERE tier = 'semantic' AND user_id = p_user_id
    ORDER BY created_at DESC
    OFFSET p_max_rows
  );

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' OR sqlstate '23P01' THEN
    RAISE;
  WHEN sqlstate '40001' OR sqlstate '40P01' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'cap_semantic_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$function$;

-- -------------------------------------------------------------------------
-- 5. evict_episodic_memory_older_than
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.evict_episodic_memory_older_than(p_user_id text, p_days integer)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
  v_count INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  IF p_user_id IS NULL OR p_user_id = '' THEN
    RAISE EXCEPTION 'evict_episodic_memory_older_than: p_user_id required' USING ERRCODE = '22023';
  END IF;

  DELETE FROM public.alpha_conversation_memory
  WHERE tier = 'episodic'
    AND user_id = p_user_id
    AND created_at < now() - make_interval(days => p_days);

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' OR sqlstate '23P01' THEN
    RAISE;
  WHEN sqlstate '40001' OR sqlstate '40P01' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'evict_episodic_memory_older_than failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$function$;

-- -------------------------------------------------------------------------
-- 6. evict_expired_working_memory
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.evict_expired_working_memory()
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
  v_count INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  DELETE FROM public.alpha_conversation_memory
  WHERE tier = 'working'
    AND persistent = false
    AND created_at < now() - interval '24 hours';

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' OR sqlstate '23P01' THEN
    RAISE;
  WHEN sqlstate '40001' OR sqlstate '40P01' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'evict_expired_working_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$function$;

-- -------------------------------------------------------------------------
-- 7. forget_memory_by_topic
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.forget_memory_by_topic(p_user_id text, p_topic text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  v_count INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  DELETE FROM public.alpha_conversation_memory
  WHERE user_id = p_user_id
    AND tier != 'semantic'
    AND (content ILIKE '%' || p_topic || '%' OR summary ILIKE '%' || p_topic || '%');

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'forget_memory_by_topic failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$function$;

-- -------------------------------------------------------------------------
-- 8. forget_working_memory
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.forget_working_memory(p_user_id text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  v_count INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  DELETE FROM public.alpha_conversation_memory
  WHERE user_id = p_user_id
    AND tier = 'working';

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'forget_working_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$function$;

-- -------------------------------------------------------------------------
-- 9. bump_memory_access
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.bump_memory_access(p_ids uuid[])
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  v_count INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  UPDATE public.alpha_conversation_memory
  SET access_count = access_count + 1,
      last_accessed_at = now()
  WHERE id = ANY(p_ids);

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'bump_memory_access failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$function$;

-- -------------------------------------------------------------------------
-- 10. get_buddy_promotion_candidates
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.get_buddy_promotion_candidates(p_user_id text)
 RETURNS TABLE(id uuid, summary text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  RETURN QUERY
    SELECT m.id, m.summary
    FROM public.alpha_conversation_memory m
    WHERE m.user_id = p_user_id
      AND m.tier = 'working'
      AND m.created_at < now() - interval '20 hours'
    LIMIT 5;
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'get_buddy_promotion_candidates failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN;
END;
$function$;

-- -------------------------------------------------------------------------
-- 11. list_active_memory_users
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.list_active_memory_users()
 RETURNS text[]
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  v_users TEXT[];
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  SELECT COALESCE(array_agg(DISTINCT user_id), ARRAY[]::TEXT[])
    INTO v_users
  FROM public.alpha_conversation_memory
  WHERE user_id IS NOT NULL;

  RETURN v_users;
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'list_active_memory_users failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN ARRAY[]::TEXT[];
END;
$function$;

-- -------------------------------------------------------------------------
-- POST-FLIGHT 1: introspection — every function body contains the new set_config line.
-- -------------------------------------------------------------------------
DO $$
DECLARE
    v_fn text;
    v_names text[] := ARRAY[
        'store_conversation_memory',
        'save_semantic_memory',
        'cap_episodic_memory',
        'cap_semantic_memory',
        'evict_episodic_memory_older_than',
        'evict_expired_working_memory',
        'forget_memory_by_topic',
        'forget_working_memory',
        'bump_memory_access',
        'get_buddy_promotion_candidates',
        'list_active_memory_users'
    ];
BEGIN
    FOREACH v_fn IN ARRAY v_names LOOP
        IF NOT EXISTS (
            SELECT 1
              FROM pg_proc
             WHERE proname = v_fn
               AND pronamespace = 'public'::regnamespace
               AND pg_get_functiondef(oid) LIKE '%set_config(''rls.role'', ''platform_admin'', true)%'
        ) THEN
            RAISE EXCEPTION 'POST-FLIGHT introspect FAILED: % missing set_config line', v_fn;
        END IF;
        RAISE NOTICE 'POST-FLIGHT introspect: % contains rls.role set_config OK', v_fn;
    END LOOP;
END $$;

-- -------------------------------------------------------------------------
-- POST-FLIGHT 2: functional smoke under jarvis_alpha_writer.
-- All writes happen inside SAVEPOINT verify_functional and are rolled back.
-- Args use bogus user_ids / uuids / topics so they match nothing in prod data.
-- -------------------------------------------------------------------------
SAVEPOINT verify_functional;

SET LOCAL ROLE jarvis_alpha_writer;

DO $$
DECLARE
    v_id_uuid     uuid;
    v_users       text[];
    v_count       integer;
    v_uuid_arr    uuid[] := ARRAY['00000000-0000-0000-0000-000000000000'::uuid];
    v_user_text   text   := 'post-flight-test-user-no-real-row';
    v_user_uuid   uuid   := '00000000-0000-0000-0000-000000000001'::uuid;
BEGIN
    -- list_active_memory_users: read-only, returns text[]
    BEGIN
        v_users := public.list_active_memory_users();
        RAISE NOTICE 'POST-FLIGHT functional: list_active_memory_users OK (returned % rows)', array_length(v_users, 1);
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: list_active_memory_users FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- get_buddy_promotion_candidates: returns TABLE; PERFORM discards it
    BEGIN
        PERFORM public.get_buddy_promotion_candidates(v_user_text);
        RAISE NOTICE 'POST-FLIGHT functional: get_buddy_promotion_candidates OK';
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: get_buddy_promotion_candidates FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- bump_memory_access: bogus uuid array → 0 rows updated, no error
    BEGIN
        v_count := public.bump_memory_access(v_uuid_arr);
        RAISE NOTICE 'POST-FLIGHT functional: bump_memory_access OK (rows=%)', v_count;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: bump_memory_access FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- forget_memory_by_topic: bogus user → 0 rows
    BEGIN
        v_count := public.forget_memory_by_topic(v_user_text, 'post-flight-topic-string');
        RAISE NOTICE 'POST-FLIGHT functional: forget_memory_by_topic OK (rows=%)', v_count;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: forget_memory_by_topic FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- forget_working_memory: bogus user → 0 rows
    BEGIN
        v_count := public.forget_working_memory(v_user_text);
        RAISE NOTICE 'POST-FLIGHT functional: forget_working_memory OK (rows=%)', v_count;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: forget_working_memory FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- evict_expired_working_memory: zero-arg; may delete real stale rows in test DB,
    -- but the outer SAVEPOINT will roll back those deletes.
    BEGIN
        v_count := public.evict_expired_working_memory();
        RAISE NOTICE 'POST-FLIGHT functional: evict_expired_working_memory OK (rows=%)', v_count;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: evict_expired_working_memory FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- evict_episodic_memory_older_than: bogus user → 0 rows
    BEGIN
        v_count := public.evict_episodic_memory_older_than(v_user_text, 365);
        RAISE NOTICE 'POST-FLIGHT functional: evict_episodic_memory_older_than OK (rows=%)', v_count;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: evict_episodic_memory_older_than FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- cap_episodic_memory: bogus user → 0 rows
    BEGIN
        v_count := public.cap_episodic_memory(v_user_text, 100);
        RAISE NOTICE 'POST-FLIGHT functional: cap_episodic_memory OK (rows=%)', v_count;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: cap_episodic_memory FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- cap_semantic_memory: bogus user → 0 rows
    BEGIN
        v_count := public.cap_semantic_memory(v_user_text, 100);
        RAISE NOTICE 'POST-FLIGHT functional: cap_semantic_memory OK (rows=%)', v_count;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: cap_semantic_memory FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- save_semantic_memory: writes a row; SAVEPOINT rolls it back.
    BEGIN
        PERFORM public.save_semantic_memory(v_user_uuid, 'POST-FLIGHT test fact — rolled back', 'preference');
        RAISE NOTICE 'POST-FLIGHT functional: save_semantic_memory OK';
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: save_semantic_memory FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- store_conversation_memory: writes a row; SAVEPOINT rolls it back.
    -- embedding=NULL is allowed (column is nullable).
    BEGIN
        v_id_uuid := public.store_conversation_memory(
            v_user_text,
            'post-flight-test-session',
            'user',
            'POST-FLIGHT verification summary — rolled back by savepoint',
            NULL::vector,
            'working',
            false,
            0.5
        );
        RAISE NOTICE 'POST-FLIGHT functional: store_conversation_memory OK (id=%)', v_id_uuid;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: store_conversation_memory FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;
END $$;

RESET ROLE;

ROLLBACK TO SAVEPOINT verify_functional;
