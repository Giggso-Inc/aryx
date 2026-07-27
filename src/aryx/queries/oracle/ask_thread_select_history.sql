-- Oracle ADB 23ai: gg_messages' request-tracking column is QUERY_ID here
-- (see ask_thread_list_messages.sql's note).
-- Params: :1=thread_id :2=request_id :3=thread_id :4=limit_pairs*2
WITH current_message AS (
    SELECT sequence_number
    FROM gg_messages
    WHERE thread_id = :1
      AND query_id = :2
      AND message_type = 'user'
      AND is_visible = 1
    ORDER BY sequence_number ASC
    FETCH FIRST 1 ROWS ONLY
),
recent_messages AS (
    SELECT message_type, content, sequence_number
    FROM gg_messages
    WHERE thread_id = :3
      AND message_type IN ('user', 'system')
      AND is_visible = 1
      AND sequence_number < COALESCE((SELECT sequence_number FROM current_message), 2147483647)
    ORDER BY sequence_number DESC
    FETCH FIRST :4 ROWS ONLY
)
SELECT message_type, content
FROM recent_messages
ORDER BY sequence_number ASC
