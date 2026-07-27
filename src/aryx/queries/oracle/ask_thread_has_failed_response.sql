-- Oracle ADB 23ai: was there a failed 'system' response for this request?
-- Params: :1=thread_id :2=request_id
SELECT 1
FROM gg_messages
WHERE thread_id = :1 AND query_id = :2 AND message_type = 'system'
  AND TRIM(JSON_VALUE(message_metadata, '$.error')) IS NOT NULL
FETCH FIRST 1 ROWS ONLY
