-- Oracle ADB 23ai: replace Postgres JSONB ->>'key' operators with JSON_VALUE.
-- TRIM(...) IS NULL captures "key absent" and "blank string" in one check.
SELECT
    gg_messages.id,
    gg_messages.content,
    gg_messages.message_metadata,
    gg_messages.citations,
    gg_messages.usage_metrics
FROM gg_messages
JOIN gg_threads
    ON gg_threads.id = gg_messages.thread_id
JOIN gg_channels
    ON gg_channels.id = gg_threads.channel_id
WHERE gg_messages.thread_id = :1
  AND gg_messages.query_id = :2
  AND gg_messages.message_type = 'system'
  AND gg_messages.is_visible = 1
  AND TRIM(JSON_VALUE(gg_messages.message_metadata, '$.error')) IS NULL
  AND gg_channels.workspace_id = :3
  AND gg_channels.name = :4
  AND JSON_VALUE(gg_channels.channel_settings, '$.aryx_hidden') = 'true'
ORDER BY gg_messages.sequence_number DESC, gg_messages.created_at DESC
FETCH FIRST 1 ROWS ONLY
