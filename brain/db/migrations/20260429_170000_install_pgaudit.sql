-- 20260429_170000_install_pgaudit.sql
-- Slab 1 of RLS Foundation Step 7
-- Install pgAudit extension. Pre-requisites:
--   1. scripts/build_pgaudit.sh has installed shared library + control + SQL files
--   2. scripts/configure_pgaudit.sh has set shared_preload_libraries='pgaudit'
--   3. Postgres has been restarted to pick up the preload setting
-- If any pre-req is missing, CREATE EXTENSION will fail with a clear error.
-- That is the intended behavior — no half-installs.

BEGIN;

-- Pre-flight: confirm pgaudit is loaded into the running cluster.
-- If shared_preload_libraries was not set or restart was skipped,
-- this DO block raises immediately with a clear, actionable message.
DO $preflight$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_settings
    WHERE name = 'shared_preload_libraries'
      AND setting LIKE '%pgaudit%'
  ) THEN
    RAISE EXCEPTION
      USING
        MESSAGE = 'pgaudit not present in shared_preload_libraries',
        DETAIL  = 'configure_pgaudit.sh must run AND postgres must be restarted before this migration',
        HINT    = 'Run: bash scripts/configure_pgaudit.sh; then: brew services restart postgresql@16; then: re-run this migration';
  END IF;
END
$preflight$;

-- Idempotent install
CREATE EXTENSION IF NOT EXISTS pgaudit;

-- Verify presence + capture version into a structured output
DO $verify$
DECLARE
  v_version text;
BEGIN
  SELECT extversion INTO v_version
  FROM pg_extension
  WHERE extname = 'pgaudit';

  IF v_version IS NULL THEN
    RAISE EXCEPTION
      USING
        MESSAGE = 'pgaudit extension row not found after CREATE EXTENSION',
        DETAIL  = 'Install completed but pg_extension has no row — investigate filesystem state';
  END IF;

  RAISE NOTICE 'pgaudit installed: version=%', v_version;
END
$verify$;

-- Record migration application (matches schema_migrations checksum pattern)
-- Note: the bash advisory-locked runner handles schema_migrations row insertion.
-- This SELECT is informational only, surfaces the final state in psql output.
SELECT
  extname,
  extversion,
  extnamespace::regnamespace AS schema
FROM pg_extension
WHERE extname = 'pgaudit';

COMMIT;

-- Post-commit smoke (outside transaction so any error doesn't roll back the install)
SELECT
  current_setting('pgaudit.log')           AS pgaudit_log,
  current_setting('pgaudit.log_relation')  AS pgaudit_log_relation,
  current_setting('pgaudit.log_parameter') AS pgaudit_log_parameter,
  current_setting('pgaudit.log_statement') AS pgaudit_log_statement;
