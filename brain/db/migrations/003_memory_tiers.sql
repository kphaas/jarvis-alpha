-- Extend working/episodic memory table
ALTER TABLE alpha_conversation_memory
  ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'working',
  ADD COLUMN IF NOT EXISTS importance_score FLOAT NOT NULL DEFAULT 0.5,
  ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Backfill: existing persistent=true rows → episodic
UPDATE alpha_conversation_memory
  SET tier = 'episodic'
  WHERE persistent = true;

-- Index: tier-scoped queries
CREATE INDEX IF NOT EXISTS idx_acm_tier_user
  ON alpha_conversation_memory (user_id, tier);

-- Semantic memory — always injected, never searched
CREATE TABLE IF NOT EXISTS alpha_semantic_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  fact TEXT NOT NULL,
  category TEXT NOT NULL CHECK (
    category IN ('preference','person','project','constraint','health','child_profile')
  ),
  source TEXT NOT NULL CHECK (
    source IN ('promoted','explicit','buddy')
  ),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE alpha_semantic_memory ENABLE ROW LEVEL SECURITY;

CREATE POLICY semantic_isolation ON alpha_semantic_memory
  FOR ALL
  USING (
    user_id::text = current_setting('jarvis.current_user')
    OR current_setting('jarvis.is_admin', true) = 'true'
  );

CREATE INDEX IF NOT EXISTS idx_asm_user
  ON alpha_semantic_memory (user_id);
