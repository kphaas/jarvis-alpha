-- 015_chat_rls_fix.sql
-- Add WITH CHECK clauses to chat_threads and chat_messages policies
-- so INSERTs pass RLS. Existing policies only have USING (read-side).

BEGIN;

-- chat_threads: drop and recreate both policies with WITH CHECK
DROP POLICY IF EXISTS chat_threads_isolation ON chat_threads;
DROP POLICY IF EXISTS child_thread_isolation ON chat_threads;

CREATE POLICY chat_threads_isolation ON chat_threads
FOR ALL
USING (user_id = current_setting('rls.user_id', true))
WITH CHECK (user_id = current_setting('rls.user_id', true));

CREATE POLICY child_thread_isolation ON chat_threads
FOR ALL
USING (
    current_setting('app.profile_role', true) = 'admin'
    OR owner_profile = current_setting('app.profile_id', true)
)
WITH CHECK (
    current_setting('app.profile_role', true) = 'admin'
    OR owner_profile = current_setting('app.profile_id', true)
);

-- chat_messages: same pattern
DROP POLICY IF EXISTS chat_messages_isolation ON chat_messages;
DROP POLICY IF EXISTS child_message_isolation ON chat_messages;

CREATE POLICY chat_messages_isolation ON chat_messages
FOR ALL
USING (
    thread_id IN (
        SELECT id FROM chat_threads
        WHERE user_id = current_setting('rls.user_id', true)
    )
)
WITH CHECK (
    thread_id IN (
        SELECT id FROM chat_threads
        WHERE user_id = current_setting('rls.user_id', true)
    )
);

CREATE POLICY child_message_isolation ON chat_messages
FOR ALL
USING (
    current_setting('app.profile_role', true) = 'admin'
    OR thread_id IN (
        SELECT id FROM chat_threads
        WHERE owner_profile = current_setting('app.profile_id', true)
    )
)
WITH CHECK (
    current_setting('app.profile_role', true) = 'admin'
    OR thread_id IN (
        SELECT id FROM chat_threads
        WHERE owner_profile = current_setting('app.profile_id', true)
    )
);

COMMIT;
