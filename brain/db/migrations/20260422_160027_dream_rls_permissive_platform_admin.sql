BEGIN;

SET LOCAL jarvis.role = 'platform_admin';

DROP POLICY IF EXISTS dream_sessions_platform_admin ON alpha_dream_sessions;
CREATE POLICY dream_sessions_platform_admin
    ON alpha_dream_sessions
    AS PERMISSIVE
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

COMMENT ON POLICY dream_sessions_platform_admin ON alpha_dream_sessions IS
    'PERMISSIVE platform_admin access required for background services (Temporal activities, dream_cost_cap_service, dream_invariant_checker). With only the pre-existing RESTRICTIVE child_profile_scope policy, Postgres defaulted to deny-all — writes silently returned UPDATE 0. Discovered D3.3 smoke test 2026-04-22. See TD-147.';

DROP POLICY IF EXISTS dream_steps_platform_admin ON alpha_dream_steps;
CREATE POLICY dream_steps_platform_admin
    ON alpha_dream_steps
    AS PERMISSIVE
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

COMMENT ON POLICY dream_steps_platform_admin ON alpha_dream_steps IS
    'PERMISSIVE platform_admin access for Temporal activities and dream services. Table previously had zero policies + force RLS = total silent deny. Discovered D3.3 smoke test 2026-04-22. See TD-147.';

COMMIT;
