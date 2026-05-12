-- Slab 7c — Remove BYPASSRLS from jarvisbrain role
--
-- Effect: jarvisbrain no longer bypasses RLS policies. The live application
-- runtime is unaffected (services connect as jarvis_alpha_writer, which is
-- already NOBYPASSRLS). Tightens:
--   * Operator psql sessions opened as jarvisbrain
--   * Migration runner (apply_migrations.sh) — must elevate explicitly for
--     DML on FORCE-RLS tables (see TD-X46 convention follow-up)
--   * Ad-hoc admin scripts
--
-- Rollback: ALTER ROLE jarvisbrain BYPASSRLS;
--
-- Refs: Slab 7c, TD-X42 (PR #95), gap discovery 2026-05-12

BEGIN;

ALTER ROLE jarvisbrain NOBYPASSRLS;

DO $$
DECLARE
  v_bypassrls BOOLEAN;
BEGIN
  SELECT rolbypassrls INTO v_bypassrls FROM pg_roles WHERE rolname = 'jarvisbrain';
  IF v_bypassrls IS DISTINCT FROM FALSE THEN
    RAISE EXCEPTION 'BYPASSRLS removal verification failed: rolbypassrls=%', v_bypassrls;
  END IF;
END $$;

COMMIT;
