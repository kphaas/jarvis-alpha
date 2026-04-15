-- Migration: 20260414_190000_content_rating_backfill
-- Purpose: Backfill content_rating where NULL to 'all_ages' (child-safe default)

BEGIN;

UPDATE alpha_conversation_memory
SET content_rating = 'all_ages'
WHERE content_rating IS NULL;

COMMIT;
