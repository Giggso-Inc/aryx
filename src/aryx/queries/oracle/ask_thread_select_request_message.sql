-- Oracle ADB 23ai: gg_messages' request-tracking column is QUERY_ID here
-- (see ask_thread_list_messages.sql's note). Params: :1=thread_id :2=request_id
SELECT id, sequence_number, 0 AS inserted, content
FROM gg_messages
WHERE thread_id = :1
  AND query_id = :2
  AND message_type = 'user'
FETCH FIRST 1 ROWS ONLY
