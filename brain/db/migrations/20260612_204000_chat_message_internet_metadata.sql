-- Store redacted Beacon internet evidence metadata with saved Ask messages.
-- Raw page text remains in Beacon evidence storage and transient prompt context,
-- not in durable chat history.

ALTER TABLE public.chat_messages
    ADD COLUMN IF NOT EXISTS internet_metadata JSONB;

COMMENT ON COLUMN public.chat_messages.internet_metadata IS
    'Redacted Beacon metadata for Helm Ask evidence display; never stores raw fetched page text.';
