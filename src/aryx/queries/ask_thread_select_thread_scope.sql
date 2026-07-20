SELECT gg_threads.id::text
FROM gg_threads
JOIN gg_channels
    ON gg_channels.id = gg_threads.channel_id
WHERE gg_threads.id = %s::uuid
  AND gg_channels.workspace_id = %s::uuid
  AND gg_channels.name = %s
  AND COALESCE((gg_channels.channel_settings->>'aryx_hidden')::boolean, FALSE) = TRUE
LIMIT 1
