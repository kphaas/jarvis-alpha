-- Migration 009: Cost Center tables
-- alpha_subscriptions: service subscription tracking
CREATE TABLE IF NOT EXISTS alpha_subscriptions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    url          TEXT,
    cost_usd     NUMERIC(10,2) NOT NULL,
    billing      TEXT NOT NULL CHECK (billing IN ('monthly','yearly')),
    next_renewal DATE NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now()
);

-- alpha_credit_balance: Anthropic credit manual tracking (single row, upserted)
CREATE TABLE IF NOT EXISTS alpha_credit_balance (
    id          SERIAL PRIMARY KEY,
    balance_usd NUMERIC(10,2) DEFAULT 0,
    spent_usd   NUMERIC(10,6) DEFAULT 0,
    pending_usd NUMERIC(10,2) DEFAULT 0,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- alpha_power_config: editable $/kWh rate (single row)
CREATE TABLE IF NOT EXISTS alpha_power_config (
    id           SERIAL PRIMARY KEY,
    rate_per_kwh NUMERIC(6,4) DEFAULT 0.13,
    updated_at   TIMESTAMPTZ DEFAULT now()
);

INSERT INTO alpha_power_config (rate_per_kwh)
VALUES (0.13)
ON CONFLICT DO NOTHING;

-- Seed known subscriptions
INSERT INTO alpha_subscriptions (name, url, cost_usd, billing, next_renewal) VALUES
    ('Claude Max',     'https://claude.ai',       100.00, 'monthly', (date_trunc('month', now()) + interval '1 month')::date),
    ('Perplexity Pro', 'https://perplexity.ai',   200.00, 'yearly',  (date_trunc('year',  now()) + interval '1 year')::date),
    ('Cursor',         'https://cursor.sh',         20.00, 'monthly', (date_trunc('month', now()) + interval '1 month')::date)
ON CONFLICT DO NOTHING;
