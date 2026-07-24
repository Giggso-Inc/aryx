SELECT id::text, sequence_number, FALSE AS inserted, content
FROM gg_messages
WHERE thread_id = %s::uuid
  AND request_id = %s::uuid
  AND message_type = 'user'
LIMIT 1
