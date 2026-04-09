-- Migration 20260409_130000: Stage 5c buddy_agent SECURITY DEFINER wrappers
-- Adds SECDEF wrappers for the two remaining naked reads buddy_agent.py performs
-- against alpha_conversation_memory, so the buddy loop can run as jarvis_alpha_writer
-- under FORCE RLS without per-session GUC plumbing.

-- ============================================================
-- FUNCTION 1: list_active_memory_users
-- ============================================================
CREATE OR REPLACE FUNCTION public.list_active_memory_users()
RETURNS TEXT[]
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_users TEXT[];
BEGIN
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
$$;

ALTER FUNCTION public.list_active_memory_users() OWNER TO jarvisbrain;
REVOKE EXECUTE ON FUNCTION public.list_active_memory_users() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.list_active_memory_users() TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.list_active_memory_users() TO jarvisbrain;

-- ============================================================
-- FUNCTION 2: get_buddy_promotion_candidates
-- ============================================================
CREATE OR REPLACE FUNCTION public.get_buddy_promotion_candidates(
  p_user_id TEXT
) RETURNS TABLE(id UUID, summary TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
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
$$;

ALTER FUNCTION public.get_buddy_promotion_candidates(TEXT) OWNER TO jarvisbrain;
REVOKE EXECUTE ON FUNCTION public.get_buddy_promotion_candidates(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_buddy_promotion_candidates(TEXT) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.get_buddy_promotion_candidates(TEXT) TO jarvisbrain;

COMMENT ON FUNCTION public.list_active_memory_users() IS
  'Stage 5c: SECURITY DEFINER wrapper enumerating distinct memory user_ids for buddy loop.';
COMMENT ON FUNCTION public.get_buddy_promotion_candidates(TEXT) IS
  'Stage 5c: SECURITY DEFINER wrapper returning aging working-tier memories for buddy promotion alerts.';
