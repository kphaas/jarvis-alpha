-- Stage 5b — Enable FORCE ROW LEVEL SECURITY on memory tables
-- After this migration, even the table owner (jarvisbrain) is subject to RLS
-- unless the owner has BYPASSRLS (verified: jarvisbrain has BYPASSRLS=t).
-- NOBYPASSRLS roles (jarvis_alpha_writer, jarvis_alpha_app) will be fully
-- constrained by RLS policies.

ALTER TABLE public.alpha_conversation_memory FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_semantic_memory FORCE ROW LEVEL SECURITY;

COMMENT ON TABLE public.alpha_conversation_memory IS
  'Stage 5b: FORCE RLS enabled. Writers use SECURITY DEFINER functions in public.store_conversation_memory, etc. Readers use rls_connection() helper which sets jarvis.current_user.';
COMMENT ON TABLE public.alpha_semantic_memory IS
  'Stage 5b: FORCE RLS enabled. Writers use public.save_semantic_memory SECDEF. Readers use rls_connection() helper.';
