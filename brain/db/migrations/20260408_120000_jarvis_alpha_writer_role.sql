-- Migration 20260408_120000: jarvis_alpha_writer LOGIN role (Step 6.5 Stage 2)
-- Creates dormant writer role with NOBYPASSRLS for future pool cutover (Stage 5).
-- Password is set separately via scripts/set_writer_password.sh from ~/jarvis/.secrets.
-- Also preserves legacy jarvis/jarvis_app roles with explicit GRANT USAGE before REVOKE,
-- and defangs jarvis BYPASSRLS flag (TD-38 audit finding).
-- This migration must remain idempotent: safe to re-run.

-- === Part 1: Create dormant writer role ===
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
    CREATE ROLE jarvis_alpha_writer LOGIN NOBYPASSRLS;
    RAISE NOTICE 'Created role jarvis_alpha_writer (LOGIN, NOBYPASSRLS)';
  ELSE
    ALTER ROLE jarvis_alpha_writer LOGIN NOBYPASSRLS;
    RAISE NOTICE 'Role jarvis_alpha_writer already exists — attributes reconciled';
  END IF;
END
$$;

-- === Part 2: Defang legacy jarvis BYPASSRLS (TD-38) ===
-- Zero runtime risk: no active connections, zero code references per audit.
-- Prevents the role from being a RLS escape hatch once Stage 5 enables FORCE RLS.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis' AND rolbypassrls = true) THEN
    ALTER ROLE jarvis NOBYPASSRLS;
    RAISE NOTICE 'Removed BYPASSRLS from legacy role jarvis (TD-38)';
  ELSE
    RAISE NOTICE 'Legacy role jarvis already NOBYPASSRLS or does not exist — no-op';
  END IF;
END
$$;

-- === Part 3: Preserve legacy roles before REVOKE lands ===
-- Add explicit schema USAGE grant so REVOKE ALL ON SCHEMA public FROM PUBLIC does not
-- silently break anything that reconnects as these roles later.
-- Idempotent: GRANT USAGE is a no-op if already granted.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis') THEN
    GRANT USAGE ON SCHEMA public TO jarvis;
    RAISE NOTICE 'Explicit USAGE grant on public schema for legacy role jarvis';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_app') THEN
    GRANT USAGE ON SCHEMA public TO jarvis_app;
    RAISE NOTICE 'Explicit USAGE grant on public schema for legacy role jarvis_app';
  END IF;
END
$$;

-- === Part 4: Revoke from PUBLIC (defense in depth) ===
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- === Part 5: Grant schema usage to writer ===
GRANT USAGE ON SCHEMA public TO jarvis_alpha_writer;

-- === Part 6: Grant DML on all current alpha_* tables ===
DO $$
DECLARE
  t record;
BEGIN
  FOR t IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tablename LIKE 'alpha_%'
  LOOP
    EXECUTE format(
      'GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO jarvis_alpha_writer',
      t.tablename
    );
  END LOOP;
END
$$;

-- === Part 7: Grant USAGE + SELECT on all current alpha_* sequences ===
DO $$
DECLARE
  s record;
BEGIN
  FOR s IN
    SELECT sequence_name FROM information_schema.sequences
    WHERE sequence_schema = 'public' AND sequence_name LIKE 'alpha_%'
  LOOP
    EXECUTE format(
      'GRANT USAGE, SELECT ON SEQUENCE public.%I TO jarvis_alpha_writer',
      s.sequence_name
    );
  END LOOP;
END
$$;

-- === Part 8: ALTER DEFAULT PRIVILEGES — future alpha_* tables auto-inherit ===
ALTER DEFAULT PRIVILEGES FOR ROLE jarvisbrain IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jarvis_alpha_writer;

ALTER DEFAULT PRIVILEGES FOR ROLE jarvisbrain IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO jarvis_alpha_writer;

-- === Part 9: Diagnostic comment ===
COMMENT ON ROLE jarvis_alpha_writer IS
  'Dormant writer role created Step 6.5 Stage 2. Pool cutover in Stage 5. NOBYPASSRLS.';
