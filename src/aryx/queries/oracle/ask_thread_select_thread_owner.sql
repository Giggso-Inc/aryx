-- Oracle ADB 23ai: replace Postgres JSONB ->>'aryx_hidden' with JSON_VALUE.
-- aryx_hidden is a JSON boolean literal (true/false), independent of the
-- NUMBER(0/1) convention SQLAlchemy uses for native is_* columns.
SELECT
    gg_threads.id,
    gg_channels.workspace_id,
    gg_channels.name,
    CASE WHEN JSON_VALUE(gg_channels.channel_settings, '$.aryx_hidden') = 'true'
         THEN 1 ELSE 0 END AS aryx_hidden
FROM gg_threads
JOIN gg_channels
    ON gg_channels.id = gg_threads.channel_id
WHERE gg_threads.id = :1
FETCH FIRST 1 ROWS ONLY
