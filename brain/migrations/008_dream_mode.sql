-- Dream Mode schema — overnight autonomous task execution

-- One row per overnight session
CREATE TABLE IF NOT EXISTS alpha_dream_sessions (
    id              BIGSERIAL PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed','aborted','killed')),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    trigger         TEXT NOT NULL DEFAULT 'scheduled'
                    CHECK (trigger IN ('scheduled','manual','dry_run')),
    cost_budget_usd NUMERIC(8,4) NOT NULL DEFAULT 5.0000,
    cost_actual_usd NUMERIC(8,4) NOT NULL DEFAULT 0.0000,
    max_duration_s  INTEGER NOT NULL DEFAULT 14400,
    step_count      INTEGER NOT NULL DEFAULT 0,
    steps_completed INTEGER NOT NULL DEFAULT 0,
    steps_failed    INTEGER NOT NULL DEFAULT 0,
    steps_blocked   INTEGER NOT NULL DEFAULT 0,
    kill_reason     TEXT,
    summary         TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- One row per step within a session
CREATE TABLE IF NOT EXISTS alpha_dream_steps (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT NOT NULL REFERENCES alpha_dream_sessions(id) ON DELETE CASCADE,
    step_index      INTEGER NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed','blocked','skipped')),
    depends_on      INTEGER[] DEFAULT '{}',
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    agent_type      TEXT CHECK (agent_type IN ('llm','code','tool','cloud','canary')),
    model_used      TEXT,
    input_hash      TEXT,
    output_summary  TEXT,
    verification    TEXT,
    cost_usd        NUMERIC(8,4) NOT NULL DEFAULT 0.0000,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX idx_dream_sessions_status ON alpha_dream_sessions (status);
CREATE INDEX idx_dream_sessions_created ON alpha_dream_sessions (created_at DESC);
CREATE INDEX idx_dream_steps_session ON alpha_dream_steps (session_id);
CREATE INDEX idx_dream_steps_status ON alpha_dream_steps (status);

-- Unique constraint: no duplicate step_index per session
CREATE UNIQUE INDEX idx_dream_steps_session_index ON alpha_dream_steps (session_id, step_index);
