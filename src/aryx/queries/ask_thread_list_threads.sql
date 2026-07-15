SELECT
    gg_threads.id::text,
    COALESCE(NULLIF(gg_threads.title, ''), 'New chat') AS title,
    COUNT(gg_messages.id)::int AS message_count,
    COALESCE(MAX(gg_messages.created_at), gg_threads.updated_at) AS updated_at
FROM gg_threads
JOIN gg_channels
    ON gg_channels.id = gg_threads.channel_id
LEFT JOIN gg_messages
    ON gg_messages.thread_id = gg_threads.id
    AND gg_messages.is_visible = TRUE
WHERE gg_channels.workspace_id = %s::uuid
  AND gg_channels.name = %s
  AND COALESCE((gg_channels.channel_settings->>'aryx_hidden')::boolean, FALSE) = TRUE
GROUP BY gg_threads.id, gg_threads.title, gg_threads.updated_at
ORDER BY updated_at DESC
LIMIT %s
