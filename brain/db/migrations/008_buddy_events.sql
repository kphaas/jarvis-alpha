-- 008_buddy_events.sql
-- Buddy event stream tied to task graphs (replaces legacy buddy_events shape in fresh installs)

BEGIN;

CREATE TABLE IF NOT EXISTS alpha_buddy_events (
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
    graph_id    UUID NOT NULL REFERENCES alpha_task_graphs(id) ON DELETE CASCADE,
    step_id     UUID REFERENCES alpha_task_steps(id) ON DELETE SET NULL,
    message     TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    read        BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_buddy_events_read_created_at
    ON alpha_buddy_events (read, created_at);

CREATE INDEX IF NOT EXISTS idx_buddy_events_graph_id
    ON alpha_buddy_events (graph_id);

ALTER TABLE alpha_buddy_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY buddy_events_isolation ON alpha_buddy_events
    USING (
        graph_id IN (
            SELECT id FROM alpha_task_graphs
            WHERE created_by = current_setting('jarvis.current_user', TRUE)
            OR current_setting('jarvis.role', TRUE) = 'admin'
        )
    );

COMMIT;
