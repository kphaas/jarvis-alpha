-- Grant EXECUTE on all SECDEF memory functions to jarvis_alpha_app.
-- Context: rls_connection() issues SET ROLE jarvis_alpha_app. ask.py calls
-- these SECDEF functions from inside rls_connection blocks. Safe because
-- SECDEF functions run as jarvisbrain and validate caller-supplied user_id.
-- Stage-5b architectural note: jarvis_alpha_app is a formally documented
-- caller of these functions. Option 1 of the app-role-vs-writer-role decision.

BEGIN;

GRANT EXECUTE ON FUNCTION public.store_conversation_memory(
    TEXT, TEXT, TEXT, TEXT, VECTOR(768), TEXT, BOOLEAN, DOUBLE PRECISION
) TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.bump_memory_access(UUID[])
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.forget_memory_by_topic(TEXT, TEXT)
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.forget_working_memory(TEXT)
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT)
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.cap_episodic_memory(TEXT, INTEGER)
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.cap_semantic_memory(TEXT, INTEGER)
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.evict_episodic_memory_older_than(TEXT, INTEGER)
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.evict_expired_working_memory()
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.get_buddy_promotion_candidates(TEXT)
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.list_active_memory_users()
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.record_buddy_event(
    TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, JSONB
) TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.run_buddy_memory_maintenance(TEXT)
    TO jarvis_alpha_app;

GRANT EXECUTE ON FUNCTION public.sync_profile_to_user()
    TO jarvis_alpha_app;

COMMIT;
