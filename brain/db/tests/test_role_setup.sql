-- =====================================================================
-- test_role_setup.sql — Slab 5.5 Round 2 fix
--
-- Purpose: ensure a non-owner test role (jarvis_alpha_smoke) exists
--          with LOGIN, NOSUPERUSER, NOBYPASSRLS, and the minimum
--          DML grants needed to execute the smoke harness.
--
-- Why a separate role:
--   The Round 1 harness ran as 'jarvisbrain', which OWNS the alpha
--   tables. PostgreSQL bypasses RLS for table owners by default, so
--   policies were never actually enforced — Case 1 falsely passed.
--   Running rls_smoke.sql as a non-owner role with NOBYPASSRLS makes
--   the policy checks real.
--
-- Idempotency: CREATE ROLE is wrapped in a DO block that catches the
--              duplicate_object exception. GRANTs are unconditional
--              and re-issuing them is a no-op.
--
-- Execution: psql -d jarvis_alpha_test -U jarvisbrain -f test_role_setup.sql
-- =====================================================================

BEGIN;

DO $$
BEGIN
    CREATE ROLE jarvis_alpha_smoke LOGIN NOSUPERUSER NOBYPASSRLS;
EXCEPTION
    WHEN duplicate_object THEN
        RAISE NOTICE 'role jarvis_alpha_smoke already exists — skipping CREATE';
END
$$;

-- Re-assert the relevant attributes in case the role was created
-- earlier with different flags (e.g. SUPERUSER or BYPASSRLS).
ALTER ROLE jarvis_alpha_smoke LOGIN NOSUPERUSER NOBYPASSRLS;

GRANT USAGE ON SCHEMA public TO jarvis_alpha_smoke;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA public
    TO jarvis_alpha_smoke;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO jarvis_alpha_smoke;

-- Future tables/sequences created by jarvisbrain in public should also
-- be reachable by the smoke role without re-running this script.
ALTER DEFAULT PRIVILEGES FOR ROLE jarvisbrain IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jarvis_alpha_smoke;
ALTER DEFAULT PRIVILEGES FOR ROLE jarvisbrain IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO jarvis_alpha_smoke;

COMMIT;
