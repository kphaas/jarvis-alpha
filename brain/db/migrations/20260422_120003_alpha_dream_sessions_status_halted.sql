BEGIN;

SET LOCAL jarvis.role = 'platform_admin';

ALTER TABLE alpha_dream_sessions
    DROP CONSTRAINT IF EXISTS alpha_dream_sessions_status_check;

ALTER TABLE alpha_dream_sessions
    ADD CONSTRAINT alpha_dream_sessions_status_check
    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'aborted', 'killed', 'halted'));

COMMENT ON CONSTRAINT alpha_dream_sessions_status_check ON alpha_dream_sessions IS
    'Valid session statuses: pending, running, completed, failed (error), aborted (fast halt), killed (emergency halt / hard terminate), halted (graceful halt via kill switch with full cleanup).';

COMMIT;
