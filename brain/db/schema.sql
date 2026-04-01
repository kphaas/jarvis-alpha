-- ============================================================
-- jarvis_alpha schema — Alpha-1
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ── Platform ─────────────────────────────────────────────────

CREATE TABLE alpha_users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    role            TEXT NOT NULL DEFAULT 'workspace_user',
    is_child        BOOLEAN DEFAULT false,
    child_age       INT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE alpha_workspaces (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    enabled         BOOLEAN DEFAULT false,
    config          JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE alpha_workspace_users (
    workspace_id    TEXT REFERENCES alpha_workspaces(id),
    user_id         TEXT REFERENCES alpha_users(id),
    role            TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE jarvis_request_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID NOT NULL,
    workspace_id    TEXT,
    user_id         TEXT NOT NULL,
    node            TEXT NOT NULL,
    route           TEXT NOT NULL,
    method          TEXT NOT NULL,
    status_code     INT NOT NULL,
    latency_ms      INT NOT NULL,
    model           TEXT,
    cost_usd        NUMERIC(10,6),
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_request_log_workspace  ON jarvis_request_log(workspace_id);
CREATE INDEX idx_request_log_user       ON jarvis_request_log(user_id);
CREATE INDEX idx_request_log_created    ON jarvis_request_log(created_at DESC);
CREATE INDEX idx_request_log_node       ON jarvis_request_log(node);
CREATE INDEX idx_request_log_route      ON jarvis_request_log(route);

-- ── Vault ─────────────────────────────────────────────────────

CREATE TABLE vault_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    TEXT REFERENCES alpha_workspaces(id),
    uploaded_by     TEXT REFERENCES alpha_users(id),
    filename        TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    size_bytes      INT,
    classification  TEXT NOT NULL DEFAULT '40_PRIVATE',
    storage_tier    TEXT NOT NULL DEFAULT 'hot',
    local_path      TEXT,
    archive_path    TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE vault_document_permissions (
    document_id     UUID REFERENCES vault_documents(id),
    user_id         TEXT REFERENCES alpha_users(id),
    can_read        BOOLEAN DEFAULT false,
    can_search      BOOLEAN DEFAULT false,
    granted_by      TEXT REFERENCES alpha_users(id),
    created_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (document_id, user_id)
);

CREATE TABLE vault_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID REFERENCES vault_documents(id),
    chunk_index     INT NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector(384),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_vault_chunks_embedding
    ON vault_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_vault_chunks_doc ON vault_chunks(document_id);

CREATE TABLE vault_access_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID REFERENCES vault_documents(id),
    user_id         TEXT REFERENCES alpha_users(id),
    action          TEXT NOT NULL,
    query           TEXT,
    result_count    INT,
    ip_address      TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_vault_access_doc     ON vault_access_log(document_id);
CREATE INDEX idx_vault_access_user    ON vault_access_log(user_id);
CREATE INDEX idx_vault_access_created ON vault_access_log(created_at DESC);

CREATE TABLE vault_pipeline (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    TEXT REFERENCES alpha_workspaces(id),
    uploaded_by     TEXT REFERENCES alpha_users(id),
    filename        TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    size_bytes      INT,
    local_path      TEXT NOT NULL,
    stage           TEXT NOT NULL DEFAULT 'inbox',
    ai_classification       TEXT,
    ai_confidence           NUMERIC(4,3),
    confirmed_classification TEXT,
    confirmed_by    TEXT REFERENCES alpha_users(id),
    confirmed_at    TIMESTAMPTZ,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_vault_pipeline_stage     ON vault_pipeline(stage);
CREATE INDEX idx_vault_pipeline_workspace ON vault_pipeline(workspace_id);

-- ── RLS Policies ─────────────────────────────────────────────

ALTER TABLE vault_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY vault_child_filter ON vault_documents
    FOR SELECT
    USING (
        NOT (
            (SELECT is_child FROM alpha_users
             WHERE id = current_setting('jarvis.current_user', true))
            AND classification NOT IN ('10_PUBLIC', '20_PROJECTS')
        )
    );
