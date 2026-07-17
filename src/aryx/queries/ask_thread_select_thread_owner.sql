SELECT
    gg_threads.id::text,
    gg_channels.workspace_id::text,
    gg_channels.name,
    COALESCE((gg_channels.channel_settings->>'aryx_hidden')::boolean, FALSE) AS aryx_hidden
FROM gg_threads
JOIN gg_channels
    ON gg_channels.id = gg_threads.channel_id
WHERE gg_threads.id = %s::uuid
LIMIT 1
