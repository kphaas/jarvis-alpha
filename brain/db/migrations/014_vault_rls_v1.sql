-- 014_vault_rls_v1.sql
-- Vault RLS v1 — strict auth + classification-based row-level security
--
-- Decisions locked (handoff_05, step 4b):
--   Strict auth on all vault routes (no more 'anon')
--   6-tier classification model with 15_KIDS added
--   Children read 10_PUBLIC + 15_KIDS only
--   Admin read 10-40 (50_SECRETS denied via API for everyone)
--   Backfill 1 existing row with ken/personal
--
-- This migration is IDEMPOTENT.

BEGIN;

ALTER TABLE vault_documents
DROP CONSTRAINT IF EXISTS vault_documents_classification_check;

ALTER TABLE vault_documents
ADD CONSTRAINT vault_documents_classification_check
CHECK (classification IN ('10_PUBLIC', '15_KIDS', '20_PROJECTS', '30_FINANCE', '40_PRIVATE', '50_SECRETS'));

UPDATE vault_documents
SET uploaded_by = 'ken', workspace_id = 'personal'
WHERE uploaded_by IS NULL OR workspace_id IS NULL;

UPDATE vault_pipeline
SET uploaded_by = 'ken', workspace_id = 'personal'
WHERE uploaded_by IS NULL OR workspace_id IS NULL;

ALTER TABLE vault_documents ALTER COLUMN uploaded_by SET NOT NULL;
ALTER TABLE vault_documents ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE vault_pipeline ALTER COLUMN uploaded_by SET NOT NULL;
ALTER TABLE vault_pipeline ALTER COLUMN workspace_id SET NOT NULL;

DROP POLICY IF EXISTS vault_child_filter ON vault_documents;
DROP POLICY IF EXISTS vault_documents_read ON vault_documents;
DROP POLICY IF EXISTS vault_documents_write ON vault_documents;

ALTER TABLE vault_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE vault_documents FORCE ROW LEVEL SECURITY;

CREATE POLICY vault_documents_read ON vault_documents
FOR SELECT
USING (
    classification != '50_SECRETS'
    AND (
        (current_setting('app.profile_role', true) = 'admin'
         AND classification IN ('10_PUBLIC', '15_KIDS', '20_PROJECTS', '30_FINANCE', '40_PRIVATE'))
        OR
        (current_setting('app.profile_role', true) = 'child'
         AND classification IN ('10_PUBLIC', '15_KIDS'))
    )
);

CREATE POLICY vault_documents_write ON vault_documents
FOR ALL
USING (current_setting('app.profile_role', true) = 'admin')
WITH CHECK (current_setting('app.profile_role', true) = 'admin');

DROP POLICY IF EXISTS vault_pipeline_admin ON vault_pipeline;
ALTER TABLE vault_pipeline ENABLE ROW LEVEL SECURITY;
ALTER TABLE vault_pipeline FORCE ROW LEVEL SECURITY;

CREATE POLICY vault_pipeline_admin ON vault_pipeline
FOR ALL
USING (current_setting('app.profile_role', true) = 'admin')
WITH CHECK (current_setting('app.profile_role', true) = 'admin');

DROP POLICY IF EXISTS vault_access_log_admin ON vault_access_log;
ALTER TABLE vault_access_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE vault_access_log FORCE ROW LEVEL SECURITY;

CREATE POLICY vault_access_log_admin ON vault_access_log
FOR ALL
USING (current_setting('app.profile_role', true) = 'admin')
WITH CHECK (current_setting('app.profile_role', true) = 'admin');

GRANT SELECT, INSERT, UPDATE, DELETE ON vault_documents TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON vault_pipeline TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON vault_access_log TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON vault_document_permissions TO jarvis_alpha_app;

COMMIT;
