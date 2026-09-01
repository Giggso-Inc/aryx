SELECT
    messages.id::text,
    messages.content,
    messages.message_metadata,
    messages.request_id::text,
    messages.created_at
FROM aryx_sales_chat_thread AS sales_threads
JOIN gg_messages AS messages
    ON messages.thread_id = sales_threads.thread_id
WHERE sales_threads.thread_id = %s::uuid
  AND sales_threads.actor_id = %s
  AND sales_threads.workspace_id = %s
  AND sales_threads.shay_workspace_id = %s::uuid
  AND messages.message_type = 'system'
  AND messages.is_visible = TRUE
ORDER BY messages.sequence_number DESC
LIMIT 1
