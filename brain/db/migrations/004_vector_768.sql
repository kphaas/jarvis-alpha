DROP INDEX IF EXISTS hnsw_alpha_memory_embedding;

ALTER TABLE alpha_conversation_memory
  ALTER COLUMN embedding TYPE vector(768)
  USING NULL;

CREATE INDEX hnsw_alpha_memory_embedding
  ON alpha_conversation_memory
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
