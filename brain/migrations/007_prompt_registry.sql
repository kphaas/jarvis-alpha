CREATE TABLE IF NOT EXISTS alpha_prompt_registry (
    id            SERIAL PRIMARY KEY,
    prompt_id     TEXT NOT NULL,
    version       INTEGER NOT NULL,
    system_prompt TEXT NOT NULL,
    model_hint    TEXT,
    scope         TEXT NOT NULL CHECK (scope IN ('alpha', 'forge', 'global')),
    is_active     BOOLEAN DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(prompt_id, version)
);

CREATE INDEX idx_prompt_registry_active ON alpha_prompt_registry (prompt_id, is_active) WHERE is_active = true;

COMMENT ON TABLE alpha_prompt_registry IS 'Versioned system prompt templates for all JARVIS modules';

-- Seed: General Assistant v1
INSERT INTO alpha_prompt_registry (prompt_id, version, system_prompt, model_hint, scope, is_active)
VALUES (
    'general_assistant',
    1,
    'You are JARVIS, a private AI assistant built on multi-node infrastructure.

Rules:
1. Think step by step before answering.
2. Lead with the answer. No preamble.
3. Use this format when problem-solving:
   [Answer] — Direct response
   [Reasoning] — Why, in 2-3 sentences
   [Next Step] — One concrete action to take
4. If asked to compare options, present a max 3-row table:
   Option | Pros | Cons | Recommendation
5. Max 5 bullet points per response unless asked for more.
6. If unsure, say so and suggest how to find out.',
    'claude-sonnet-4-20250514',
    'alpha',
    true
)
ON CONFLICT (prompt_id, version) DO NOTHING;
