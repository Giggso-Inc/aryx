-- 0033 — Aryx Ask request idempotency on Shay messages.

ALTER TABLE gg_messages
    ADD COLUMN IF NOT EXISTS request_id UUID;

CREATE UNIQUE INDEX IF NOT EXISTS uq_gg_messages_thread_request_type
    ON gg_messages(thread_id, request_id, message_type)
    WHERE request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_gg_messages_thread_sequence
    ON gg_messages(thread_id, sequence_number);
