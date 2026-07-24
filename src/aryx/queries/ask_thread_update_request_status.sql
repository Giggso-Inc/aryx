UPDATE gg_messages
SET message_metadata = jsonb_set(
        COALESCE(message_metadata, '{}'::jsonb),
        '{request_status}',
        to_jsonb(%s::text),
        TRUE
    ),
    updated_at = NOW()
WHERE thread_id = %s::uuid
  AND request_id = %s::uuid
  AND message_type = 'user'
