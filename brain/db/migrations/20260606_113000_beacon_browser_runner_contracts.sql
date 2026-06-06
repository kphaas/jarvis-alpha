-- Purpose: Beacon P8 browser-runner event contract.
-- Adds the queued status already emitted by the browser approval handoff.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260606113000);

ALTER TABLE public.alpha_internet_tool_events
    DROP CONSTRAINT IF EXISTS alpha_internet_tool_events_status_check;

ALTER TABLE public.alpha_internet_tool_events
    ADD CONSTRAINT alpha_internet_tool_events_status_check
    CHECK (status IN ('started', 'queued', 'succeeded', 'failed', 'blocked'));

COMMENT ON CONSTRAINT alpha_internet_tool_events_status_check
    ON public.alpha_internet_tool_events
    IS 'Beacon tool event status contract. queued is used by approval handoff before execution.';

COMMIT;

-- Downgrade:
-- BEGIN;
-- ALTER TABLE public.alpha_internet_tool_events
--     DROP CONSTRAINT IF EXISTS alpha_internet_tool_events_status_check;
-- ALTER TABLE public.alpha_internet_tool_events
--     ADD CONSTRAINT alpha_internet_tool_events_status_check
--     CHECK (status IN ('started', 'succeeded', 'failed', 'blocked'));
-- COMMIT;
