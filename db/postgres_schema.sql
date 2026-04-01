-- jarvis-alpha Postgres schema
-- Alpha-0 — closes GitHub issue #1
-- All tables use UUID primary keys
-- RLS enforced via jarvis.current_user and jarvis.current_project

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- App role — never connect as superuser
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
    CREATE ROLE jarvis_alpha_app LOGIN NOINHERIT;
  END IF;
END $$;

-- Projects
CREATE TABLE IF NOT EXISTS alpha_projects (
    project_id      TEXT PRIMARY KEY,
    user_id         UUID NOT NULL,
    name            TEXT NOT NULL,
    project_type    TEXT NOT NULL CHECK (project_type IN ('forge','personal','problem')),
    forge_project_id TEXT,
    description     TEXT,
    status          TEXT DEFAULT 'active' CHECK (status IN ('active','paused','closed')),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Chat threads
CREATE TABLE IF NOT EXISTS chat_threads (
    thread_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    project_id       TEXT REFERENCES alpha_projects(project_id),
    title            TEXT NOT NULL,
    thread_type      TEXT NOT NULL CHECK (thread_type IN ('personal','project')),
    project_type     TEXT,
    created_at       TIMESTAMP DEFAULT NOW(),
    last_active_at   TIMESTAMP DEFAULT NOW(),
    archived         BOOLEAN DEFAULT FALSE,
    memory_extracted BOOLEAN DEFAULT FALSE
);

-- Chat messages
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id   UUID NOT NULL REFERENCES chat_threads(thread_id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content     TEXT NOT NULL,
    model_used  TEXT,
    tokens_used INTEGER,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Thread memory extracts
CREATE TABLE IF NOT EXISTS thread_memory_extracts (
    extract_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id              UUID NOT NULL,
    user_id                UUID NOT NULL,
    project_id             TEXT,
    summary                TEXT NOT NULL,
    key_facts              JSONB,
    embedding              vector(384),
    extracted_at           TIMESTAMP DEFAULT NOW(),
    promoted_to_long_term  BOOLEAN DEFAULT FALSE
);

-- Thread retention prompts
CREATE TABLE IF NOT EXISTS thread_retention_prompts (
    prompt_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id      UUID NOT NULL REFERENCES chat_threads(thread_id),
    user_id        UUID NOT NULL,
    triggered_at   TIMESTAMP DEFAULT NOW(),
    user_response  TEXT CHECK (user_response IN ('extract_and_delete','keep','delete_only','snooze')),
    responded_at   TIMESTAMP,
    snoozed_until  TIMESTAMP,
    last_notified_at TIMESTAMP
);

-- TaskGraph
CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_task_id UUID,
    project_id     TEXT,
    user_id        UUID NOT NULL,
    title          TEXT NOT NULL,
    status         TEXT DEFAULT 'pending' CHECK (status IN ('pending','in_progress','complete','failed','deferred')),
    priority       INTEGER DEFAULT 3,
    created_at     TIMESTAMP DEFAULT NOW(),
    updated_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS task_steps (
    step_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id     UUID NOT NULL REFERENCES agent_tasks(task_id) ON DELETE CASCADE,
    step_order  INTEGER NOT NULL,
    model_used  TEXT,
    tool        TEXT,
    input_json  JSONB,
    output_ref  TEXT,
    status      TEXT DEFAULT 'pending' CHECK (status IN ('pending','in_progress','complete','failed')),
    error       TEXT,
    started_at  TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER
);

-- Execution state (per-step memory snapshots)
CREATE TABLE IF NOT EXISTS execution_state (
    state_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    step_id      UUID NOT NULL REFERENCES task_steps(step_id) ON DELETE CASCADE,
    context_json JSONB,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- Conversation memory (extended from jarvis-core)
CREATE TABLE IF NOT EXISTS conversation_memory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    project_id      TEXT,
    summary         TEXT NOT NULL,
    structured_data JSONB,
    embedding       vector(384),
    memory_type     TEXT DEFAULT 'general',
    source          TEXT DEFAULT 'live' CHECK (source IN ('live','thread_extract','overnight','ingest')),
    source_thread_id UUID,
    access_count    INTEGER DEFAULT 0,
    promoted        BOOLEAN DEFAULT FALSE,
    expires_at      TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Buddy state
CREATE TABLE IF NOT EXISTS buddy_state (
    buddy_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL,
    last_seen         TIMESTAMP,
    pending_reminders JSONB,
    task_context      JSONB,
    alerts            JSONB,
    heartbeat_at      TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT NOW()
);

-- Secret access log
CREATE TABLE IF NOT EXISTS secret_access_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service     TEXT NOT NULL,
    secret_name TEXT NOT NULL,
    source      TEXT NOT NULL,
    called_at   TIMESTAMP DEFAULT NOW(),
    caller_ip   TEXT
);

-- Routing decisions
CREATE TABLE IF NOT EXISTS routing_decisions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id      UUID,
    step_id      UUID,
    model_used   TEXT,
    tool         TEXT,
    decision_json JSONB,
    latency_ms   INTEGER,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- Cloud costs
CREATE TABLE IF NOT EXISTS cloud_costs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model       TEXT NOT NULL,
    cost_usd    NUMERIC(10,6) NOT NULL,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    task_id     UUID,
    step_id     UUID,
    agent_id    TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_chat_threads_user     ON chat_threads(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_threads_project  ON chat_threads(project_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_thread  ON chat_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status    ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_task_steps_task       ON task_steps(task_id);
CREATE INDEX IF NOT EXISTS idx_conv_memory_user      ON conversation_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_conv_memory_source    ON conversation_memory(source);
CREATE INDEX IF NOT EXISTS idx_buddy_state_user      ON buddy_state(user_id);

-- HNSW index for vector search
CREATE INDEX IF NOT EXISTS idx_conv_memory_embedding
    ON conversation_memory USING hnsw (embedding vector_cosine_ops);

-- RLS
ALTER TABLE chat_threads        ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages       ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_tasks         ENABLE ROW LEVEL SECURITY;
ALTER TABLE buddy_state         ENABLE ROW LEVEL SECURITY;

CREATE POLICY thread_isolation ON chat_threads
    USING (user_id::text = current_setting('jarvis.current_user', true));

CREATE POLICY message_isolation ON chat_messages
    USING (thread_id IN (
        SELECT thread_id FROM chat_threads
        WHERE user_id::text = current_setting('jarvis.current_user', true)
    ));

CREATE POLICY memory_isolation ON conversation_memory
    USING (user_id::text = current_setting('jarvis.current_user', true));

CREATE POLICY task_isolation ON agent_tasks
    USING (user_id::text = current_setting('jarvis.current_user', true));

CREATE POLICY buddy_isolation ON buddy_state
    USING (user_id::text = current_setting('jarvis.current_user', true));
