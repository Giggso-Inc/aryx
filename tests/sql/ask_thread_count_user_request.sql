SELECT COUNT(*)
FROM gg_messages
WHERE thread_id = %s
  AND request_id = %s
  AND message_type = 'user'
