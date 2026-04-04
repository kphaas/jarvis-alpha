-- Optional: run manually if not using Brain startup ensure_table().
CREATE TABLE IF NOT EXISTS secret_access_log (
    id              BIGSERIAL PRIMARY KEY,
    key_name        TEXT NOT NULL,
    source          TEXT NOT NULL,
    accessed_at     TIMESTAMPTZ NOT NULL,
    node            TEXT NOT NULL,
    flushed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sal_key ON secret_access_log(key_name);
CREATE INDEX IF NOT EXISTS idx_sal_accessed ON secret_access_log(accessed_at DESC);
