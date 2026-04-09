-- Migration 20260409_100000: Stage 5a MemoryService SECURITY DEFINER wrappers
-- Adds SECDEF wrappers for all MemoryService writes before FORCE RLS cutover.

-- ============================================================
-- FUNCTION 1: store_conversation_memory
-- ============================================================
CREATE OR REPLACE FUNCTION public.store_conversation_memory(
  p_user_id TEXT,
  p_session_id TEXT,
  p_role TEXT,
  p_summary TEXT,
  p_embedding VECTOR(768),
  p_tier TEXT,
  p_persistent BOOLEAN,
  p_importance DOUBLE PRECISION
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_id UUID;
BEGIN
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
$$;

ALTER FUNCTION public.store_conversation_memory(TEXT, TEXT, TEXT, TEXT, VECTOR(768), TEXT, BOOLEAN, DOUBLE PRECISION) OWNER TO jarvisbrain;
REVOKE EXECUTE ON FUNCTION public.store_conversation_memory(TEXT, TEXT, TEXT, TEXT, VECTOR(768), TEXT, BOOLEAN, DOUBLE PRECISION) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.store_conversation_memory(TEXT, TEXT, TEXT, TEXT, VECTOR(768), TEXT, BOOLEAN, DOUBLE PRECISION) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.store_conversation_memory(TEXT, TEXT, TEXT, TEXT, VECTOR(768), TEXT, BOOLEAN, DOUBLE PRECISION) TO jarvisbrain;

-- ============================================================
-- FUNCTION 2: save_semantic_memory
-- ============================================================
CREATE OR REPLACE FUNCTION public.save_semantic_memory(
  p_user_id UUID,
  p_fact TEXT,
  p_category TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_inserted INTEGER;
BEGIN
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
$$;

ALTER FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT) OWNER TO jarvisbrain;
REVOKE EXECUTE ON FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT) TO jarvisbrain;

-- ============================================================
-- FUNCTION 3: bump_memory_access
-- ============================================================
CREATE OR REPLACE FUNCTION public.bump_memory_access(
  p_ids UUID[]
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_count INTEGER;
BEGIN
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
$$;

ALTER FUNCTION public.bump_memory_access(UUID[]) OWNER TO jarvisbrain;
REVOKE EXECUTE ON FUNCTION public.bump_memory_access(UUID[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bump_memory_access(UUID[]) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.bump_memory_access(UUID[]) TO jarvisbrain;

-- ============================================================
-- FUNCTION 4: forget_memory_by_topic
-- ============================================================
CREATE OR REPLACE FUNCTION public.forget_memory_by_topic(
  p_user_id TEXT,
  p_topic TEXT
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_count INTEGER;
BEGIN
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
$$;

ALTER FUNCTION public.forget_memory_by_topic(TEXT, TEXT) OWNER TO jarvisbrain;
REVOKE EXECUTE ON FUNCTION public.forget_memory_by_topic(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.forget_memory_by_topic(TEXT, TEXT) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.forget_memory_by_topic(TEXT, TEXT) TO jarvisbrain;

-- ============================================================
-- FUNCTION 5: forget_working_memory
-- ============================================================
CREATE OR REPLACE FUNCTION public.forget_working_memory(
  p_user_id TEXT
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_count INTEGER;
BEGIN
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
$$;

ALTER FUNCTION public.forget_working_memory(TEXT) OWNER TO jarvisbrain;
REVOKE EXECUTE ON FUNCTION public.forget_working_memory(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.forget_working_memory(TEXT) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.forget_working_memory(TEXT) TO jarvisbrain;

COMMENT ON FUNCTION public.store_conversation_memory(TEXT, TEXT, TEXT, TEXT, VECTOR(768), TEXT, BOOLEAN, DOUBLE PRECISION) IS
  'Stage 5a: SECURITY DEFINER wrapper for MemoryService conversation inserts.';
COMMENT ON FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT) IS
  'Stage 5a: SECURITY DEFINER wrapper for MemoryService semantic saves with cap enforcement.';
COMMENT ON FUNCTION public.bump_memory_access(UUID[]) IS
  'Stage 5a: SECURITY DEFINER wrapper for episodic access bump updates.';
COMMENT ON FUNCTION public.forget_memory_by_topic(TEXT, TEXT) IS
  'Stage 5a: SECURITY DEFINER wrapper for /forget topic deletes.';
COMMENT ON FUNCTION public.forget_working_memory(TEXT) IS
  'Stage 5a: SECURITY DEFINER wrapper for /forget working-tier deletes.';
