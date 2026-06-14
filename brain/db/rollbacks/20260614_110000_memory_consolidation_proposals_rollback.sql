-- Rollback: ADR-0026 reviewed consolidation proposal infrastructure.
-- Fails safely if proposal or ledger rows already exist.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260614110000);

DO $precheck$
BEGIN
    IF to_regclass('public.alpha_memory_consolidation_execution_ledger') IS NOT NULL
       AND EXISTS (
           SELECT 1
             FROM public.alpha_memory_consolidation_execution_ledger
            LIMIT 1
       ) THEN
        RAISE EXCEPTION
            'Refusing rollback: alpha_memory_consolidation_execution_ledger contains rows';
    END IF;

    IF to_regclass('public.alpha_memory_consolidation_proposals') IS NOT NULL
       AND EXISTS (
           SELECT 1
             FROM public.alpha_memory_consolidation_proposals
            LIMIT 1
       ) THEN
        RAISE EXCEPTION
            'Refusing rollback: alpha_memory_consolidation_proposals contains rows';
    END IF;
END
$precheck$;

DROP TABLE IF EXISTS public.alpha_memory_consolidation_execution_ledger;
DROP TABLE IF EXISTS public.alpha_memory_consolidation_proposals;

COMMIT;
