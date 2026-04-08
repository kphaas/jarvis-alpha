-- Migration 20260408_130000: SECURITY DEFINER functions (Step 6.5 Stage 3)
-- Wraps background writers for alpha_buddy_events, alpha_conversation_memory, alpha_semantic_memory
-- All functions owned by jarvisbrain (superuser), SECURITY DEFINER, schema-qualified bodies
-- Perplexity validation applied: SET LOCAL timeouts, REVOKE PUBLIC, re-raise 08xxx

-- ============================================================
-- FUNCTION 1: record_buddy_event
-- Inserts into alpha_buddy_events. Audit-critical — re-raises on error.
-- ============================================================
CREATE OR REPLACE FUNCTION public.record_buddy_event(
  p_user_id TEXT,
  p_event_type TEXT,
  p_title TEXT,
  p_body TEXT,
  p_priority TEXT,
  p_source TEXT,
  p_payload JSONB
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_id BIGINT;
BEGIN
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';
  
  -- Validate user_id: must be 'system' sentinel or non-empty string
  IF p_user_id IS NULL OR p_user_id = '' THEN
    RAISE EXCEPTION 'record_buddy_event: p_user_id must be non-null (use ''system'' sentinel for system events)'
      USING ERRCODE = '22023';
  END IF;
  
  INSERT INTO public.alpha_buddy_events
    (user_id, event_type, title, body, priority, source, payload)
  VALUES
    (p_user_id, p_event_type, p_title, p_body, p_priority, p_source, p_payload)
  RETURNING id INTO v_id;
  
  RETURN v_id;
EXCEPTION
  WHEN OTHERS THEN
    -- Audit-critical: re-raise all errors so caller sees them
    RAISE;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB) TO jarvisbrain;

-- ============================================================
-- FUNCTION 2: evict_expired_working_memory
-- Deletes working-tier rows past expires_at. Maintenance op.
-- ============================================================
CREATE OR REPLACE FUNCTION public.evict_expired_working_memory()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_count INTEGER;
BEGIN
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';
  
  DELETE FROM public.alpha_conversation_memory
  WHERE tier = 'working' AND expires_at < now();
  
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
$$;

REVOKE EXECUTE ON FUNCTION public.evict_expired_working_memory() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.evict_expired_working_memory() TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.evict_expired_working_memory() TO jarvisbrain;

-- ============================================================
-- FUNCTION 3: evict_episodic_memory_older_than
-- ============================================================
CREATE OR REPLACE FUNCTION public.evict_episodic_memory_older_than(
  p_user_id TEXT,
  p_days INTEGER
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_count INTEGER;
BEGIN
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
$$;

REVOKE EXECUTE ON FUNCTION public.evict_episodic_memory_older_than(TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.evict_episodic_memory_older_than(TEXT, INTEGER) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.evict_episodic_memory_older_than(TEXT, INTEGER) TO jarvisbrain;

-- ============================================================
-- FUNCTION 4: cap_episodic_memory
-- Keeps top N episodic rows by recency per user
-- ============================================================
CREATE OR REPLACE FUNCTION public.cap_episodic_memory(
  p_user_id TEXT,
  p_max_rows INTEGER
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_count INTEGER;
BEGIN
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
$$;

REVOKE EXECUTE ON FUNCTION public.cap_episodic_memory(TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cap_episodic_memory(TEXT, INTEGER) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.cap_episodic_memory(TEXT, INTEGER) TO jarvisbrain;

-- ============================================================
-- FUNCTION 5: cap_semantic_memory
-- Caps semantic rows in alpha_conversation_memory (legacy dual-table pattern)
-- ============================================================
CREATE OR REPLACE FUNCTION public.cap_semantic_memory(
  p_user_id TEXT,
  p_max_rows INTEGER
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_count INTEGER;
BEGIN
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
$$;

REVOKE EXECUTE ON FUNCTION public.cap_semantic_memory(TEXT, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cap_semantic_memory(TEXT, INTEGER) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.cap_semantic_memory(TEXT, INTEGER) TO jarvisbrain;

-- ============================================================
-- FUNCTION 6: promote_episodic_to_semantic
-- Scores episodic rows, inserts top-scored into alpha_semantic_memory
-- ============================================================
CREATE OR REPLACE FUNCTION public.promote_episodic_to_semantic(
  p_user_id TEXT
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_count INTEGER;
BEGIN
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '30s';
  
  IF p_user_id IS NULL OR p_user_id = '' THEN
    RAISE EXCEPTION 'promote_episodic_to_semantic: p_user_id required' USING ERRCODE = '22023';
  END IF;
  
  -- Promotion logic: insert high-access-count episodic rows into semantic table
  -- Score threshold: access_count >= 3 (matches current buddy logic)
  INSERT INTO public.alpha_semantic_memory (user_id, content, embedding, source_memory_id, created_at)
  SELECT user_id, content, embedding, id, now()
  FROM public.alpha_conversation_memory
  WHERE tier = 'episodic'
    AND user_id = p_user_id
    AND access_count >= 3
    AND id NOT IN (
      SELECT source_memory_id FROM public.alpha_semantic_memory
      WHERE source_memory_id IS NOT NULL AND user_id = p_user_id
    )
  ON CONFLICT DO NOTHING;
  
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' OR sqlstate '23P01' THEN
    RAISE;
  WHEN sqlstate '40001' OR sqlstate '40P01' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'promote_episodic_to_semantic failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.promote_episodic_to_semantic(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.promote_episodic_to_semantic(TEXT) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.promote_episodic_to_semantic(TEXT) TO jarvisbrain;

-- ============================================================
-- FUNCTION 7: run_buddy_memory_maintenance (OMNIBUS)
-- Calls evict_working, evict_episodic(30d), cap_episodic(1000), cap_semantic(200), promote
-- Inner try/catch per step — continues on failure, returns JSONB counts
-- ============================================================
CREATE OR REPLACE FUNCTION public.run_buddy_memory_maintenance(
  p_user_id TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_evicted_working INTEGER := 0;
  v_evicted_episodic INTEGER := 0;
  v_capped_episodic INTEGER := 0;
  v_capped_semantic INTEGER := 0;
  v_promoted INTEGER := 0;
  v_errors JSONB := '[]'::jsonb;
BEGIN
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '60s';
  
  IF p_user_id IS NULL OR p_user_id = '' THEN
    RAISE EXCEPTION 'run_buddy_memory_maintenance: p_user_id required' USING ERRCODE = '22023';
  END IF;
  
  -- Step 1: evict expired working memory (not user-scoped — global operation)
  BEGIN
    v_evicted_working := public.evict_expired_working_memory();
  EXCEPTION WHEN OTHERS THEN
    v_errors := v_errors || jsonb_build_object('step', 'evict_working', 'error', SQLERRM);
  END;
  
  -- Step 2: evict episodic older than 30 days
  BEGIN
    v_evicted_episodic := public.evict_episodic_memory_older_than(p_user_id, 30);
  EXCEPTION WHEN OTHERS THEN
    v_errors := v_errors || jsonb_build_object('step', 'evict_episodic', 'error', SQLERRM);
  END;
  
  -- Step 3: cap episodic at 1000 rows
  BEGIN
    v_capped_episodic := public.cap_episodic_memory(p_user_id, 1000);
  EXCEPTION WHEN OTHERS THEN
    v_errors := v_errors || jsonb_build_object('step', 'cap_episodic', 'error', SQLERRM);
  END;
  
  -- Step 4: cap semantic at 200 rows
  BEGIN
    v_capped_semantic := public.cap_semantic_memory(p_user_id, 200);
  EXCEPTION WHEN OTHERS THEN
    v_errors := v_errors || jsonb_build_object('step', 'cap_semantic', 'error', SQLERRM);
  END;
  
  -- Step 5: promote episodic to semantic
  BEGIN
    v_promoted := public.promote_episodic_to_semantic(p_user_id);
  EXCEPTION WHEN OTHERS THEN
    v_errors := v_errors || jsonb_build_object('step', 'promote', 'error', SQLERRM);
  END;
  
  RETURN jsonb_build_object(
    'user_id', p_user_id,
    'evicted_working', v_evicted_working,
    'evicted_episodic', v_evicted_episodic,
    'capped_episodic', v_capped_episodic,
    'capped_semantic', v_capped_semantic,
    'promoted', v_promoted,
    'errors', v_errors
  );
END;
$$;

REVOKE EXECUTE ON FUNCTION public.run_buddy_memory_maintenance(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.run_buddy_memory_maintenance(TEXT) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.run_buddy_memory_maintenance(TEXT) TO jarvisbrain;

-- ============================================================
-- Diagnostic: comment on each function
-- ============================================================
COMMENT ON FUNCTION public.record_buddy_event IS 'Step 6.5 Stage 3: SECURITY DEFINER wrapper for alpha_buddy_events writes. Re-raises all errors (audit-critical).';
COMMENT ON FUNCTION public.evict_expired_working_memory IS 'Step 6.5 Stage 3: deletes working-tier memory past expires_at. Maintenance op.';
COMMENT ON FUNCTION public.evict_episodic_memory_older_than IS 'Step 6.5 Stage 3: deletes user episodic memory older than N days.';
COMMENT ON FUNCTION public.cap_episodic_memory IS 'Step 6.5 Stage 3: keeps top N episodic rows per user by recency.';
COMMENT ON FUNCTION public.cap_semantic_memory IS 'Step 6.5 Stage 3: keeps top N semantic rows in alpha_conversation_memory per user.';
COMMENT ON FUNCTION public.promote_episodic_to_semantic IS 'Step 6.5 Stage 3: promotes high-access episodic rows to alpha_semantic_memory.';
COMMENT ON FUNCTION public.run_buddy_memory_maintenance IS 'Step 6.5 Stage 3: omnibus maintenance. Calls all 5 memory ops with inner try/catch. Returns JSONB counts.';
