WITH stats AS (
    SELECT
        COUNT(*)::int AS message_count,
        MAX(created_at) AS last_message_at
    FROM gg_messages
    WHERE thread_id = %s::uuid
      AND is_visible = TRUE
)
UPDATE gg_threads
SET message_count = stats.message_count,
    last_message_at = stats.last_message_at,
    updated_at = NOW()
FROM stats
WHERE gg_threads.id = %s::uuid
