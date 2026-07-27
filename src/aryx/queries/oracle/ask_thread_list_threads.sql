-- Oracle ADB 23ai: replace Postgres JSONB ->>'aryx_hidden' with JSON_VALUE.
-- TRIM(...) IS NULL captures "key absent" (NULL) and "blank string" in one
-- check -- Oracle has no true empty string, so it doubles as the NULLIF/BTRIM
-- idiom the Postgres version needs two functions for.
SELECT
    gg_threads.id,
    COALESCE(NULLIF(gg_threads.title, ' '), 'New chat') AS title,
    COUNT(gg_messages.id) AS message_count,
    COALESCE(MAX(gg_messages.created_at), gg_threads.updated_at) AS updated_at
FROM gg_threads
JOIN gg_channels
    ON gg_channels.id = gg_threads.channel_id
LEFT JOIN gg_messages
    ON gg_messages.thread_id = gg_threads.id
    AND gg_messages.is_visible = 1
WHERE gg_channels.workspace_id = :1
  AND gg_channels.name = :2
  AND JSON_VALUE(gg_channels.channel_settings, '$.aryx_hidden') = 'true'
GROUP BY gg_threads.id, gg_threads.title, gg_threads.updated_at
ORDER BY updated_at DESC
FETCH FIRST :3 ROWS ONLY
