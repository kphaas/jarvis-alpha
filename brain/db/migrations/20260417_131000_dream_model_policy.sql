BEGIN;

CREATE TABLE IF NOT EXISTS alpha_dream_model_policy (
    goal_type           TEXT PRIMARY KEY,
    planner_provider    TEXT NOT NULL
                        CHECK (planner_provider IN ('anthropic', 'google', 'openai', 'perplexity', 'ollama')),
    planner_model       TEXT NOT NULL,
    planner_family      TEXT NOT NULL
                        CHECK (planner_family IN ('claude', 'gemini', 'gpt', 'sonar', 'llama')),
    reviewer_provider   TEXT NOT NULL
                        CHECK (reviewer_provider IN ('anthropic', 'google', 'openai', 'perplexity', 'ollama')),
    reviewer_model      TEXT NOT NULL,
    reviewer_family     TEXT NOT NULL
                        CHECK (reviewer_family IN ('claude', 'gemini', 'gpt', 'sonar', 'llama')),
    max_revisions       INTEGER NOT NULL DEFAULT 3 CHECK (max_revisions BETWEEN 0 AND 5),
    cost_multiplier     NUMERIC(4,2) NOT NULL DEFAULT 2.5 CHECK (cost_multiplier >= 1.0),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (planner_family <> reviewer_family)
);

INSERT INTO alpha_dream_model_policy (
    goal_type,
    planner_provider, planner_model, planner_family,
    reviewer_provider, reviewer_model, reviewer_family,
    max_revisions, cost_multiplier
) VALUES (
    'default',
    'anthropic', 'claude-haiku-4-5-20251001', 'claude',
    'google',    'gemini-2.5-flash',         'gemini',
    3, 2.50
) ON CONFLICT (goal_type) DO NOTHING;

ALTER TABLE alpha_dream_model_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_dream_model_policy FORCE ROW LEVEL SECURITY;

CREATE POLICY dream_model_policy_isolation ON alpha_dream_model_policy
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

GRANT SELECT ON alpha_dream_model_policy TO jarvis_alpha_writer;

COMMIT;
