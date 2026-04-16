-- =============================================================================
-- Migration: Model pricing table
-- =============================================================================
-- Creates alpha_model_pricing for per-model, per-date token pricing.
-- No seed data — pricing managed via scripts/seed_pricing.py or Settings UI.
-- Cost-event route degrades gracefully when pricing is missing.
--
-- Design: Langfuse model-definitions pattern + Stripe date-keyed pricing.
-- Never UPDATE rows — INSERT new effective_from for price changes.
--
-- Query pattern:
--   SELECT input_per_1m_usd, output_per_1m_usd
--   FROM alpha_model_pricing
--   WHERE provider = $1 AND model = $2 AND effective_from <= now()::date
--   ORDER BY effective_from DESC LIMIT 1;

BEGIN;

CREATE TABLE IF NOT EXISTS alpha_model_pricing (
  id                              BIGSERIAL PRIMARY KEY,
  provider                        TEXT NOT NULL,
  model                           TEXT NOT NULL,
  input_per_1m_usd                NUMERIC(10, 6) NOT NULL,
  output_per_1m_usd               NUMERIC(10, 6) NOT NULL,
  context_threshold_tokens        INTEGER,
  input_per_1m_usd_long_context   NUMERIC(10, 6),
  output_per_1m_usd_long_context  NUMERIC(10, 6),
  effective_from                  DATE NOT NULL DEFAULT CURRENT_DATE,
  source                          TEXT,
  notes                           TEXT,
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, model, effective_from)
);

COMMENT ON TABLE alpha_model_pricing IS
  'Per-provider, per-model token pricing with date-keyed history. Never UPDATE — INSERT new effective_from for price changes. Seeded via scripts/seed_pricing.py, not migrations.';

COMMENT ON COLUMN alpha_model_pricing.input_per_1m_usd IS
  'Input price per 1M tokens, USD. Base rate (ctx <= context_threshold_tokens).';

COMMENT ON COLUMN alpha_model_pricing.output_per_1m_usd IS
  'Output price per 1M tokens, USD. Base rate.';

COMMENT ON COLUMN alpha_model_pricing.context_threshold_tokens IS
  'If set, input above this uses *_long_context rates. NULL = flat rate.';

COMMENT ON COLUMN alpha_model_pricing.input_per_1m_usd_long_context IS
  'Input price per 1M above context_threshold_tokens. NULL if flat.';

COMMENT ON COLUMN alpha_model_pricing.output_per_1m_usd_long_context IS
  'Output price per 1M above context_threshold_tokens. NULL if flat.';

COMMENT ON COLUMN alpha_model_pricing.effective_from IS
  'Date this price becomes effective. Pricing lookup uses most recent row <= call date.';

COMMENT ON COLUMN alpha_model_pricing.source IS
  'Verification source URL. E.g. platform.claude.com/pricing';

CREATE INDEX IF NOT EXISTS idx_model_pricing_lookup
  ON alpha_model_pricing (provider, model, effective_from DESC);

COMMIT;


-- =============================================================================
-- Rollback (run manually if needed):
-- =============================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS idx_model_pricing_lookup;
-- DROP TABLE IF EXISTS alpha_model_pricing;
-- COMMIT;
