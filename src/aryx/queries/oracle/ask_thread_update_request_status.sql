-- Oracle ADB 23ai: gg_messages' request-tracking column is QUERY_ID here
-- (see ask_thread_list_messages.sql's note).
-- JSON_OBJECT(... VALUE :1) safely builds a JSON object from the bind var
-- (no string concatenation/injection risk), then JSON_MERGEPATCH sets just
-- the request_status key, preserving the rest of message_metadata --
-- equivalent to Postgres's jsonb_set(..., '{request_status}', ..., TRUE).
-- Params: :1=status :2=thread_id :3=request_id
UPDATE gg_messages
SET message_metadata = JSON_MERGEPATCH(
        NVL(message_metadata, '{}'),
        JSON_OBJECT('request_status' VALUE :1)
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE thread_id = :2
  AND query_id = :3
  AND message_type = 'user'
