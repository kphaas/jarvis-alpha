-- 008b_task_events.sql
-- Task graph event stream (admin-session visibility via RLS)

BEGIN;

CREATE TABLE IF NOT EXISTS alpha_task_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  TEXT NOT NULL
        CHECK (event_type IN (
            'graph_complete',
            'graph_halted',
            'step_failed',
            'step_retrying',
            'ci_required',
            'approval_required'
        )),
    graph_id    UUID REFERENCES alpha_task_graphs(id) ON DELETE CASCADE,
    step_id     UUID REFERENCES alpha_task_steps(id) ON DELETE CASCADE,
    message     TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    read        BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_task_events_read_created_at
    ON alpha_task_events (read, created_at);

CREATE INDEX IF NOT EXISTS idx_task_events_graph_id
    ON alpha_task_events (graph_id);

ALTER TABLE alpha_task_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY task_events_isolation ON alpha_task_events
    USING (current_setting('jarvis.current_user', TRUE) = 'admin');

COMMIT;
