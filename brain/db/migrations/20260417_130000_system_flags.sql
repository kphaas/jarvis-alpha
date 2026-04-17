BEGIN;

CREATE TABLE IF NOT EXISTS alpha_system_flags (
    flag_name   TEXT PRIMARY KEY,
    flag_value  BOOLEAN NOT NULL DEFAULT FALSE,
    reason      TEXT,
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO alpha_system_flags (flag_name, flag_value, reason) VALUES
    ('dream_mode_killed', FALSE, 'Mid-run kill switch for Dream Mode. Set TRUE to abort immediately.'),
    ('overnight_execution_paused', FALSE, 'Pause all overnight execution (maintenance mode).')
ON CONFLICT (flag_name) DO NOTHING;

ALTER TABLE alpha_system_flags ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_system_flags FORCE ROW LEVEL SECURITY;

CREATE POLICY system_flags_isolation ON alpha_system_flags
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

GRANT SELECT, UPDATE ON alpha_system_flags TO jarvis_alpha_writer;

COMMIT;
