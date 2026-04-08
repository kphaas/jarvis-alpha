-- Migration 20260408_150000: Stage 3 final fix
-- 1. DROP promote_episodic_to_semantic (schema mismatch — see TD-40)
-- 2. Fix evict_expired_working_memory SQL to match real alpha_conversation_memory schema
-- 3. Shrink run_buddy_memory_maintenance omnibus to 4 ops (remove promote step)

-- ============================================================
-- Drop promote function (TD-40: redesign for production)
-- ============================================================
DROP FUNCTION IF EXISTS public.promote_episodic_to_semantic(TEXT);

-- ============================================================
-- Fix evict_expired_working_memory
-- Real schema: no expires_at column. Use tier + persistent + created_at.
-- Rule: working-tier rows older than 24h, not marked persistent → evict.
-- TODO: make the 24h TTL configurable when memory goes production.
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
$$;

COMMENT ON FUNCTION public.evict_expired_working_memory IS 
  'Step 6.5 Stage 3 (fixed 20260408_150000): deletes working-tier memory older than 24h and not persistent. TODO: configurable TTL when memory goes production.';

-- ============================================================
-- Shrink omnibus: remove promote step (was Step 5)
-- Now 4 ops: evict_working, evict_episodic_30d, cap_episodic, cap_semantic
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
  v_errors JSONB := '[]'::jsonb;
BEGIN
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '60s';
  
  IF p_user_id IS NULL OR p_user_id = '' THEN
    RAISE EXCEPTION 'run_buddy_memory_maintenance: p_user_id required' USING ERRCODE = '22023';
  END IF;
  
  -- Step 1: evict expired working memory (global op, not user-scoped)
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
  
  -- NOTE: promote step removed 20260408_150000 — see TD-40
  
  RETURN jsonb_build_object(
    'user_id', p_user_id,
    'evicted_working', v_evicted_working,
    'evicted_episodic', v_evicted_episodic,
    'capped_episodic', v_capped_episodic,
    'capped_semantic', v_capped_semantic,
    'errors', v_errors
  );
END;
$$;

COMMENT ON FUNCTION public.run_buddy_memory_maintenance IS 
  'Step 6.5 Stage 3 (shrunk 20260408_150000): omnibus memory maintenance. 4 ops: evict_working, evict_episodic_30d, cap_episodic(1000), cap_semantic(200). Promote removed — see TD-40.';
