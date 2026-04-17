BEGIN;

CREATE TABLE IF NOT EXISTS alpha_dream_allowed_paths (
    id              SERIAL PRIMARY KEY,
    path_glob       TEXT NOT NULL UNIQUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    enabled         BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO alpha_dream_allowed_paths (path_glob, notes) VALUES
    ('brain/services/*.py', 'Service modules on Brain'),
    ('tests/**/*.py', 'Test files — any depth'),
    ('tests/**/*.sql', 'Test SQL fixtures')
ON CONFLICT (path_glob) DO NOTHING;

CREATE TABLE IF NOT EXISTS alpha_dream_blocked_writes (
    id                  BIGSERIAL PRIMARY KEY,
    dream_step_id       UUID,
    goal_id             UUID,
    attempted_path      TEXT NOT NULL,
    attempted_diff      TEXT NOT NULL,
    block_reason        TEXT NOT NULL,
    block_rule          TEXT NOT NULL,
    blocked_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_blocked_writes_goal ON alpha_dream_blocked_writes(goal_id);
CREATE INDEX idx_blocked_writes_time ON alpha_dream_blocked_writes(blocked_at DESC);

ALTER TABLE alpha_dream_blocked_writes ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_dream_blocked_writes FORCE ROW LEVEL SECURITY;

CREATE POLICY blocked_writes_isolation ON alpha_dream_blocked_writes
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

GRANT SELECT, INSERT ON alpha_dream_blocked_writes TO jarvis_alpha_writer;
GRANT USAGE, SELECT ON SEQUENCE alpha_dream_blocked_writes_id_seq TO jarvis_alpha_writer;
GRANT SELECT ON alpha_dream_allowed_paths TO jarvis_alpha_writer;

COMMIT;
