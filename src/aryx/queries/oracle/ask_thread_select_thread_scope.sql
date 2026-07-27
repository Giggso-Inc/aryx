-- Oracle ADB 23ai: replace Postgres JSONB ->>'aryx_hidden' with JSON_VALUE.
SELECT gg_threads.id
FROM gg_threads
JOIN gg_channels
    ON gg_channels.id = gg_threads.channel_id
WHERE gg_threads.id = :1
  AND gg_channels.workspace_id = :2
  AND gg_channels.name = :3
  AND JSON_VALUE(gg_channels.channel_settings, '$.aryx_hidden') = 'true'
FETCH FIRST 1 ROWS ONLY
