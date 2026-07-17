SELECT
    gg_messages.id::text,
    gg_messages.content,
    gg_messages.message_metadata,
    gg_messages.citations,
    gg_messages.usage_metrics
FROM gg_messages
JOIN gg_threads
    ON gg_threads.id = gg_messages.thread_id
JOIN gg_channels
    ON gg_channels.id = gg_threads.channel_id
WHERE gg_messages.thread_id = %s::uuid
  AND gg_messages.request_id = %s::uuid
  AND gg_messages.message_type = 'system'
  AND gg_messages.is_visible = TRUE
  AND NULLIF(BTRIM(COALESCE(gg_messages.message_metadata->>'error', '')), '') IS NULL
  AND gg_channels.workspace_id = %s::uuid
  AND gg_channels.name = %s
  AND COALESCE((gg_channels.channel_settings->>'aryx_hidden')::boolean, FALSE) = TRUE
ORDER BY gg_messages.sequence_number DESC, gg_messages.created_at DESC
LIMIT 1
