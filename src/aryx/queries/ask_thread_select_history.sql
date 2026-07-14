WITH current_message AS (
    SELECT sequence_number
    FROM gg_messages
    WHERE thread_id = %s::uuid
      AND request_id = %s::uuid
      AND message_type = 'user'
    ORDER BY sequence_number ASC
    LIMIT 1
),
recent_messages AS (
    SELECT message_type, content, sequence_number
    FROM gg_messages
    WHERE thread_id = %s::uuid
      AND message_type IN ('user', 'system')
      AND sequence_number < COALESCE((SELECT sequence_number FROM current_message), 2147483647)
    ORDER BY sequence_number DESC
    LIMIT %s
)
SELECT message_type, content
FROM recent_messages
ORDER BY sequence_number ASC
