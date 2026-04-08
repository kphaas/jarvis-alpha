-- Migration: alpha_briefings table
-- Purpose: Store morning briefings from forge overnight batches and manual runs
-- Retention: 5 years active, then archive to cold storage (future jarvis-alpha cron)

CREATE TABLE IF NOT EXISTS alpha_briefings (
    id              SERIAL PRIMARY KEY,
    batch_run_id    TEXT NOT NULL UNIQUE,
    briefing_date   DATE NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    source          TEXT NOT NULL,
    summary         JSONB NOT NULL,
    results         JSONB NOT NULL,
    markdown        TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alpha_briefings_date
    ON alpha_briefings(briefing_date DESC);

CREATE INDEX IF NOT EXISTS idx_alpha_briefings_source
    ON alpha_briefings(source);

CREATE INDEX IF NOT EXISTS idx_alpha_briefings_started_at
    ON alpha_briefings(started_at DESC);

COMMENT ON TABLE alpha_briefings IS
    'Briefings from overnight batches and manual runs. 5yr retention then archive.';

COMMENT ON COLUMN alpha_briefings.batch_run_id IS
    'Format: YYYYMMDD_HHMM_XXXX where XXXX is 4 random hex chars';

COMMENT ON COLUMN alpha_briefings.source IS
    'forge_overnight | forge_manual | forge_ci | buddy_alert';
