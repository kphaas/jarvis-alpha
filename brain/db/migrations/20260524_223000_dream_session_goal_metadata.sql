-- Dream Mode Temporal goal metadata.
-- Stores the planner/reviewer inputs on alpha_dream_sessions so a pending row
-- can be started later by the Temporal worker without request-body memory.

BEGIN;

ALTER TABLE public.alpha_dream_sessions
    ADD COLUMN IF NOT EXISTS goal_type TEXT NOT NULL DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS goal_text TEXT,
    ADD COLUMN IF NOT EXISTS prompt_version TEXT NOT NULL DEFAULT 'v1',
    ADD COLUMN IF NOT EXISTS recent_context TEXT,
    ADD COLUMN IF NOT EXISTS prior_lessons TEXT,
    ADD COLUMN IF NOT EXISTS review_verdict TEXT
        CHECK (review_verdict IS NULL OR review_verdict IN ('APPROVED', 'REJECTED', 'NEEDS_REVISION')),
    ADD COLUMN IF NOT EXISTS review_reasoning TEXT,
    ADD COLUMN IF NOT EXISTS review_issues JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN public.alpha_dream_sessions.goal_type IS
    'Model policy key used by Dream planner/reviewer activities.';
COMMENT ON COLUMN public.alpha_dream_sessions.goal_text IS
    'Operator or scheduler goal text handed to the Dream planner activity.';
COMMENT ON COLUMN public.alpha_dream_sessions.prompt_version IS
    'Prompt registry version used by planner/reviewer activities.';
COMMENT ON COLUMN public.alpha_dream_sessions.recent_context IS
    'Optional context block passed to the Dream planner.';
COMMENT ON COLUMN public.alpha_dream_sessions.prior_lessons IS
    'Optional lessons block passed to the Dream planner.';
COMMENT ON COLUMN public.alpha_dream_sessions.review_verdict IS
    'Final reviewer verdict for the approved/rejected persisted plan.';
COMMENT ON COLUMN public.alpha_dream_sessions.review_reasoning IS
    'Reviewer reasoning for the final persisted verdict.';
COMMENT ON COLUMN public.alpha_dream_sessions.review_issues IS
    'Reviewer issues for the final persisted verdict.';

COMMIT;
