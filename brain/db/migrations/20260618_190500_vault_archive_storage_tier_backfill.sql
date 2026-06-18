-- 20260618_190500_vault_archive_storage_tier_backfill.sql
-- Keep vault document storage_tier aligned with the archive-confirm result.
-- Earlier confirms updated local_path/status but left storage_tier at the
-- initial hot value, making search metadata disagree with archive metadata.

UPDATE public.vault_documents
   SET storage_tier = 'unraid'
 WHERE status = 'archived'
   AND local_path LIKE 'unraid:%'
   AND storage_tier IS DISTINCT FROM 'unraid';

UPDATE public.vault_documents
   SET storage_tier = 'nvme_only'
 WHERE status = 'archived'
   AND local_path NOT LIKE 'unraid:%'
   AND storage_tier = 'hot';
