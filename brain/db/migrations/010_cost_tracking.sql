-- Migration 010: Cost tracking tables

-- alpha_cloud_costs: every cloud API call logged here
CREATE TABLE IF NOT EXISTS alpha_cloud_costs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider         TEXT NOT NULL CHECK (provider IN ('anthropic','gemini','perplexity')),
    model            TEXT NOT NULL,
    prompt_tokens    INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens     INTEGER DEFAULT 0,
    cost_usd         NUMERIC(10,6) DEFAULT 0,
    session_type     TEXT CHECK (session_type IN ('ask','overnight','forge','other')),
    key_name         TEXT,
    intent           TEXT,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cloud_costs_provider ON alpha_cloud_costs(provider);
CREATE INDEX IF NOT EXISTS idx_cloud_costs_created ON alpha_cloud_costs(created_at);
CREATE INDEX IF NOT EXISTS idx_cloud_costs_session ON alpha_cloud_costs(session_type);

-- alpha_budget_config: per-provider monthly limits
CREATE TABLE IF NOT EXISTS alpha_budget_config (
    id               SERIAL PRIMARY KEY,
    provider         TEXT UNIQUE NOT NULL,
    monthly_limit_usd NUMERIC(10,2) DEFAULT 50.00,
    updated_at       TIMESTAMPTZ DEFAULT now()
);

INSERT INTO alpha_budget_config (provider, monthly_limit_usd) VALUES
    ('anthropic',  50.00),
    ('gemini',     20.00),
    ('perplexity', 10.00)
ON CONFLICT (provider) DO NOTHING;

-- alpha_hardware_config: node hardware costs + depreciation
CREATE TABLE IF NOT EXISTS alpha_hardware_config (
    id               SERIAL PRIMARY KEY,
    node_name        TEXT UNIQUE NOT NULL,
    cost_usd         NUMERIC(10,2) NOT NULL,
    years            INTEGER NOT NULL DEFAULT 4,
    monthly_usd      NUMERIC(10,2) GENERATED ALWAYS AS (cost_usd / (years * 12)) STORED,
    updated_at       TIMESTAMPTZ DEFAULT now()
);

INSERT INTO alpha_hardware_config (node_name, cost_usd, years) VALUES
    ('Brain',    2500.00, 4),
    ('Gateway',  1000.00, 4),
    ('Endpoint', 1000.00, 4),
    ('Sandbox',   600.00, 4)
ON CONFLICT (node_name) DO NOTHING;

-- alpha_perplexity_credit: manual Perplexity credit tracking
CREATE TABLE IF NOT EXISTS alpha_perplexity_credit (
    id           SERIAL PRIMARY KEY,
    balance_usd  NUMERIC(10,2) DEFAULT 0,
    spent_usd    NUMERIC(10,6) DEFAULT 0,
    updated_at   TIMESTAMPTZ DEFAULT now()
);

INSERT INTO alpha_perplexity_credit (balance_usd, spent_usd)
VALUES (4.84, 0.13)
ON CONFLICT DO NOTHING;
