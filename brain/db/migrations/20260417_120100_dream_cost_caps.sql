BEGIN;

CREATE TABLE IF NOT EXISTS alpha_dream_cost_caps (
    scope           TEXT PRIMARY KEY
                    CHECK (scope IN ('per_step', 'per_session', 'per_night', 'per_week', 'per_model_day')),
    limit_usd       NUMERIC(10,4) NOT NULL CHECK (limit_usd >= 0),
    notes           TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO alpha_dream_cost_caps (scope, limit_usd, notes) VALUES
    ('per_step',        0.50,  'Max cost per single dream step'),
    ('per_session',     2.00,  'Max cost per goal execution'),
    ('per_night',       5.00,  'Max cost per overnight run'),
    ('per_week',       25.00,  'Max cost per 7-day rolling window'),
    ('per_model_day',   3.00,  'Max cost per provider per day')
ON CONFLICT (scope) DO NOTHING;

CREATE TABLE IF NOT EXISTS alpha_dream_cost_counters (
    id              BIGSERIAL PRIMARY KEY,
    scope           TEXT NOT NULL,
    scope_key       TEXT NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL,
    window_end      TIMESTAMPTZ NOT NULL,
    spent_usd       NUMERIC(10,6) NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope, scope_key, window_start)
);

CREATE INDEX idx_cost_counters_lookup
    ON alpha_dream_cost_counters (scope, scope_key, window_start, window_end);

ALTER TABLE alpha_dream_cost_caps ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_dream_cost_caps FORCE ROW LEVEL SECURITY;
ALTER TABLE alpha_dream_cost_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_dream_cost_counters FORCE ROW LEVEL SECURITY;

CREATE POLICY cost_caps_isolation ON alpha_dream_cost_caps
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

CREATE POLICY cost_counters_isolation ON alpha_dream_cost_counters
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

GRANT SELECT ON alpha_dream_cost_caps TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE ON alpha_dream_cost_counters TO jarvis_alpha_writer;
GRANT USAGE, SELECT ON SEQUENCE alpha_dream_cost_counters_id_seq TO jarvis_alpha_writer;

COMMIT;
