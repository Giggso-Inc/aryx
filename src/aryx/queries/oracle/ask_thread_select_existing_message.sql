-- Oracle ADB 23ai: check for an existing message row by the same unique key
-- Postgres enforces via its partial index (thread_id, request_id, message_type)
-- WHERE request_id IS NOT NULL. Params: :1=thread_id :2=request_id :3=message_type
SELECT id, sequence_number, content, message_metadata, updated_at
FROM gg_messages
WHERE thread_id = :1 AND query_id = :2 AND message_type = :3
FETCH FIRST 1 ROWS ONLY
