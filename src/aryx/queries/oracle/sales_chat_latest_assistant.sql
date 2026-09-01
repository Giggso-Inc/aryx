-- Oracle ADB 23ai: is_visible is NUMBER(0/1) here (SQLAlchemy's Oracle
-- Boolean), not TRUE/FALSE -- see ask_thread_list_messages.sql for the
-- same convention on the same gg_messages table.
SELECT
    messages.id,
    messages.content,
    messages.message_metadata,
    messages.request_id,
    messages.created_at
FROM aryx_sales_chat_thread sales_threads
JOIN gg_messages messages
    ON messages.thread_id = sales_threads.thread_id
WHERE sales_threads.thread_id = :1
  AND sales_threads.actor_id = :2
  AND sales_threads.workspace_id = :3
  AND sales_threads.shay_workspace_id = :4
  AND messages.message_type = 'system'
  AND messages.is_visible = 1
ORDER BY messages.sequence_number DESC
FETCH FIRST 1 ROW ONLY
