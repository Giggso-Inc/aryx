-- Oracle ADB 23ai: replace Postgres JSONB ->>'aryx_hidden' with JSON_VALUE
-- (matches ask_thread_list_threads.sql's override for the same column);
-- is_visible is NUMBER(0/1) here, not TRUE/FALSE.
SELECT
    threads.id,
    COALESCE(NULLIF(threads.title, ' '), 'New chat') AS title,
    COUNT(messages.id) AS message_count,
    COALESCE(MAX(messages.created_at), threads.updated_at) AS updated_at
FROM aryx_sales_chat_thread sales_threads
JOIN gg_threads threads
    ON threads.id = sales_threads.thread_id
JOIN gg_channels channels
    ON channels.id = threads.channel_id
LEFT JOIN gg_messages messages
    ON messages.thread_id = threads.id
    AND messages.is_visible = 1
WHERE sales_threads.actor_id = :1
  AND sales_threads.workspace_id = :2
  AND sales_threads.shay_workspace_id = :3
  AND channels.workspace_id = sales_threads.shay_workspace_id
  AND channels.name = :4
  AND JSON_VALUE(channels.channel_settings, '$.aryx_hidden') = 'true'
GROUP BY threads.id, threads.title, threads.updated_at
ORDER BY updated_at DESC
FETCH FIRST :5 ROWS ONLY
