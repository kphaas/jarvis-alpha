-- Stage 5b hotfix — grant jarvis_alpha_app role membership to jarvis_alpha_writer
-- Without this, rls_connection() fails on SET ROLE because writer is not a superuser.
-- Verified live via manual GRANT on 2026-04-09 — this migration persists it.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_auth_members am
    JOIN pg_roles r ON r.oid = am.roleid
    JOIN pg_roles m ON m.oid = am.member
    WHERE r.rolname = 'jarvis_alpha_app'
      AND m.rolname = 'jarvis_alpha_writer'
  ) THEN
    GRANT jarvis_alpha_app TO jarvis_alpha_writer;
  END IF;
END $$;
