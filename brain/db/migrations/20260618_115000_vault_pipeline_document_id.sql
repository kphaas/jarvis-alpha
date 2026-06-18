-- 20260618_115000_vault_pipeline_document_id.sql
--
-- Add the vault_pipeline.document_id column required by the vault confirm and
-- ingestion routes. The route writes the document id at upload time; this
-- migration backfills older pipeline rows where a matching document can be
-- identified.

\set ON_ERROR_STOP on
\timing on

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

SELECT pg_advisory_xact_lock(20260618115000);

ALTER TABLE public.vault_pipeline
  ADD COLUMN IF NOT EXISTS document_id uuid;

ALTER TABLE public.vault_documents
  ADD COLUMN IF NOT EXISTS status text;

UPDATE public.vault_documents
SET status = CASE
  WHEN archive_path IS NOT NULL THEN 'archived'
  ELSE 'uploaded'
END
WHERE status IS NULL;

ALTER TABLE public.vault_documents
  ALTER COLUMN status SET DEFAULT 'uploaded',
  ALTER COLUMN status SET NOT NULL;

WITH candidates AS (
  SELECT
    vp.id AS pipeline_id,
    vd.id AS document_id,
    row_number() OVER (
      PARTITION BY vp.id
      ORDER BY
        CASE WHEN vd.local_path = vp.local_path THEN 0 ELSE 1 END,
        vd.created_at DESC NULLS LAST,
        vd.id
    ) AS rn
  FROM public.vault_pipeline vp
  JOIN public.vault_documents vd
    ON vd.workspace_id = vp.workspace_id
   AND (
        vd.local_path = vp.local_path
        OR vd.filename = vp.filename
   )
  WHERE vp.document_id IS NULL
)
UPDATE public.vault_pipeline vp
SET document_id = candidates.document_id
FROM candidates
WHERE vp.id = candidates.pipeline_id
  AND candidates.rn = 1;

ALTER TABLE public.vault_pipeline
  DROP CONSTRAINT IF EXISTS vault_pipeline_document_id_fkey;

ALTER TABLE public.vault_pipeline
  ADD CONSTRAINT vault_pipeline_document_id_fkey
  FOREIGN KEY (document_id)
  REFERENCES public.vault_documents(id)
  ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_vault_pipeline_document_id
  ON public.vault_pipeline(document_id);

COMMIT;
