CREATE TABLE IF NOT EXISTS alpha_honeypot_events (
    id          BIGSERIAL PRIMARY KEY,
    trap_path   TEXT NOT NULL,
    source_ip   TEXT NOT NULL,
    method      TEXT NOT NULL,
    user_agent  TEXT,
    headers     JSONB DEFAULT '{}',
    captured_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_honeypot_captured_at ON alpha_honeypot_events (captured_at DESC);
CREATE INDEX idx_honeypot_trap_path ON alpha_honeypot_events (trap_path);
