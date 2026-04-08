-- Child profiles + content rating enforcement

-- Profile table — one row per user/child
CREATE TABLE IF NOT EXISTS alpha_profiles (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('admin', 'child')),
    child_age    INTEGER,
    max_rating   TEXT NOT NULL DEFAULT 'all_ages'
                 CHECK (max_rating IN ('all_ages', 'age_8_plus', 'teen', 'adult')),
    pin_hash     TEXT NOT NULL,
    active       BOOLEAN DEFAULT true,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- Add content_rating to tables that need filtering
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS content_rating TEXT NOT NULL DEFAULT 'adult'
    CHECK (content_rating IN ('all_ages', 'age_8_plus', 'teen', 'adult'));

ALTER TABLE chat_threads
    ADD COLUMN IF NOT EXISTS owner_profile TEXT REFERENCES alpha_profiles(id),
    ADD COLUMN IF NOT EXISTS content_rating TEXT NOT NULL DEFAULT 'adult'
    CHECK (content_rating IN ('all_ages', 'age_8_plus', 'teen', 'adult'));

ALTER TABLE alpha_conversation_memory
    ADD COLUMN IF NOT EXISTS content_rating TEXT NOT NULL DEFAULT 'adult'
    CHECK (content_rating IN ('all_ages', 'age_8_plus', 'teen', 'adult'));

ALTER TABLE alpha_task_graphs
    ADD COLUMN IF NOT EXISTS owner_profile TEXT REFERENCES alpha_profiles(id);

ALTER TABLE alpha_dream_sessions
    ADD COLUMN IF NOT EXISTS owner_profile TEXT REFERENCES alpha_profiles(id);

-- Rating severity function — higher number = more restricted
CREATE OR REPLACE FUNCTION rating_level(r TEXT) RETURNS INTEGER AS $$
    SELECT CASE r
        WHEN 'all_ages'   THEN 1
        WHEN 'age_8_plus' THEN 2
        WHEN 'teen'       THEN 3
        WHEN 'adult'      THEN 4
        ELSE 0
    END;
$$ LANGUAGE sql IMMUTABLE;

-- RLS policies for child profile isolation

-- chat_threads: children only see their own threads
CREATE POLICY child_thread_isolation ON chat_threads
    FOR ALL
    USING (
        current_setting('app.profile_role', true) = 'admin'
        OR owner_profile = current_setting('app.profile_id', true)
    );

-- chat_messages: children only see messages in threads they own
CREATE POLICY child_message_isolation ON chat_messages
    FOR ALL
    USING (
        current_setting('app.profile_role', true) = 'admin'
        OR thread_id IN (
            SELECT id FROM chat_threads
            WHERE owner_profile = current_setting('app.profile_id', true)
        )
    );

-- chat_messages: content rating filter
CREATE POLICY child_content_rating ON chat_messages
    FOR SELECT
    USING (
        current_setting('app.profile_role', true) = 'admin'
        OR rating_level(content_rating) <= rating_level(current_setting('app.max_rating', true))
    );

-- alpha_conversation_memory: children see only age-appropriate memory
CREATE POLICY child_memory_rating ON alpha_conversation_memory
    FOR SELECT
    USING (
        current_setting('app.profile_role', true) = 'admin'
        OR rating_level(content_rating) <= rating_level(current_setting('app.max_rating', true))
    );

-- alpha_conversation_memory: children cannot write
CREATE POLICY child_memory_write ON alpha_conversation_memory
    FOR INSERT
    WITH CHECK (
        current_setting('app.profile_role', true) = 'admin'
    );

-- alpha_task_graphs: children cannot create or modify tasks
CREATE POLICY child_task_isolation ON alpha_task_graphs
    FOR ALL
    USING (
        current_setting('app.profile_role', true) = 'admin'
    );

-- alpha_dream_sessions: children cannot access dream mode
CREATE POLICY child_dream_isolation ON alpha_dream_sessions
    FOR ALL
    USING (
        current_setting('app.profile_role', true) = 'admin'
    );

-- alpha_dream_steps: children cannot access dream steps
CREATE POLICY child_dream_step_isolation ON alpha_dream_steps
    FOR ALL
    USING (
        current_setting('app.profile_role', true) = 'admin'
    );

-- Enable RLS on tables that don't have it yet
ALTER TABLE chat_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_task_graphs ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_dream_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_dream_steps ENABLE ROW LEVEL SECURITY;

-- Seed profiles (PINs will be set via the auth route — these are placeholders)
-- Ken's PIN hash will be migrated from ALPHA_PIN
-- Child PINs set by Ken later
INSERT INTO alpha_profiles (id, display_name, role, child_age, max_rating, pin_hash)
VALUES
    ('ken', 'Ken', 'admin', NULL, 'adult', 'PLACEHOLDER_MIGRATE_FROM_ALPHA_PIN'),
    ('ryleigh', 'Ryleigh', 'child', 8, 'age_8_plus', 'PLACEHOLDER_SET_BY_KEN'),
    ('sloane', 'Sloane', 'child', 5, 'all_ages', 'PLACEHOLDER_SET_BY_KEN')
ON CONFLICT (id) DO NOTHING;

-- Index
CREATE INDEX IF NOT EXISTS idx_profiles_role ON alpha_profiles (role);
CREATE INDEX IF NOT EXISTS idx_chat_threads_owner ON chat_threads (owner_profile);
CREATE INDEX IF NOT EXISTS idx_chat_messages_rating ON chat_messages (content_rating);
