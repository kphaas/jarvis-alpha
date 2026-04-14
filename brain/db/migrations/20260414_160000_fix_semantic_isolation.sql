-- Fix jarvis.is_admin orphan in semantic_isolation policy.
-- jarvis.is_admin is never set by any writer. Admin bypass was silently
-- non-functional. Replace with canonical jarvis.role = 'platform_admin'.

BEGIN;

DROP POLICY IF EXISTS semantic_isolation ON public.alpha_semantic_memory;

CREATE POLICY semantic_isolation ON public.alpha_semantic_memory
    FOR ALL
    USING (
        (user_id)::text = current_setting('jarvis.current_user', true)
        OR current_setting('jarvis.role', true) = 'platform_admin'
    );

COMMIT;
