SELECT
    threads.id::text,
    COALESCE(NULLIF(threads.title, ''), 'New chat') AS title,
    COUNT(messages.id)::int AS message_count,
    COALESCE(MAX(messages.created_at), threads.updated_at) AS updated_at
FROM aryx_sales_chat_thread AS sales_threads
JOIN gg_threads AS threads
    ON threads.id = sales_threads.thread_id
JOIN gg_channels AS channels
    ON channels.id = threads.channel_id
LEFT JOIN gg_messages AS messages
    ON messages.thread_id = threads.id
    AND messages.is_visible = TRUE
WHERE sales_threads.actor_id = %s
  AND sales_threads.workspace_id = %s
  AND sales_threads.shay_workspace_id = %s::uuid
  AND channels.workspace_id = sales_threads.shay_workspace_id
  AND channels.name = %s
  AND COALESCE((channels.channel_settings->>'aryx_hidden')::boolean, FALSE) = TRUE
GROUP BY threads.id, threads.title, threads.updated_at
ORDER BY updated_at DESC
LIMIT %s
