-- ============================================================
-- 012_watchdog_events.sql — Service health monitoring events
-- ============================================================
-- Stores state changes from the watchdog agent.
-- NOT every health check — only state transitions and actions.
-- Pattern: append-only, 30-day retention handled by Buddy cleanup.

CREATE TABLE IF NOT EXISTS alpha_watchdog_events (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_name         TEXT NOT NULL,
    node                 TEXT NOT NULL,
    event_type           TEXT NOT NULL,
    previous_state       TEXT,
    current_state        TEXT,
    consecutive_failures INT DEFAULT 0,
    latency_ms           NUMERIC(10,2),
    http_status          INT,
    error_message        TEXT,
    action_taken         TEXT,
    trace_id             UUID,
    created_at           TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT watchdog_event_type_check CHECK (
        event_type IN (
            'down',
            'restored',
            'degraded',
            'restart_triggered',
            'restart_succeeded',
            'restart_failed',
            'check_error'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_watchdog_events_service_time
    ON alpha_watchdog_events(service_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_watchdog_events_type_time
    ON alpha_watchdog_events(event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_watchdog_events_node
    ON alpha_watchdog_events(node, created_at DESC);

ALTER TABLE alpha_watchdog_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY watchdog_events_read ON alpha_watchdog_events
    FOR SELECT
    USING (true);

CREATE POLICY watchdog_events_system_write ON alpha_watchdog_events
    FOR INSERT
    WITH CHECK (current_setting('rls.user_id', true) = 'system');

GRANT SELECT ON alpha_watchdog_events TO jarvis_alpha_app;
GRANT INSERT ON alpha_watchdog_events TO jarvis_alpha_app;
