-- Purpose: Let Ask users pin important threads while excluding stale
-- unpinned threads from the active cap after 30 days.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260615214500);

ALTER TABLE public.chat_threads
    ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_chat_threads_user_pinned
    ON public.chat_threads(user_id, updated_at DESC)
    WHERE archived_at IS NULL AND pinned = TRUE;

COMMENT ON COLUMN public.chat_threads.pinned IS
    'User-controlled Ask thread retention flag; pinned threads continue counting toward active caps.';

COMMIT;
