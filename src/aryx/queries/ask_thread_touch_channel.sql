UPDATE gg_channels
SET message_count = (
        SELECT COUNT(*)::int
        FROM gg_messages
        JOIN gg_threads ON gg_threads.id = gg_messages.thread_id
        WHERE gg_threads.channel_id = %s::uuid
          AND gg_messages.is_visible = TRUE
    ),
    last_message_at = (
        SELECT MAX(gg_messages.created_at)
        FROM gg_messages
        JOIN gg_threads ON gg_threads.id = gg_messages.thread_id
        WHERE gg_threads.channel_id = %s::uuid
          AND gg_messages.is_visible = TRUE
    ),
    updated_at = NOW()
WHERE id = %s::uuid
