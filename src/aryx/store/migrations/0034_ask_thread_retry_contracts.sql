-- 0034 — Complete Ask retry claims and guarantee the channel upsert target.
-- migration: required

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM gg_channels
        WHERE name IS NOT NULL
          AND workspace_id IS NOT NULL
        GROUP BY name, workspace_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Migration 0034 cannot enforce channel uniqueness: duplicate (name, workspace_id) rows exist';
    END IF;
END
$migration$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_gg_channels_name_workspace
    ON gg_channels(name, workspace_id);

UPDATE gg_messages AS user_message
SET message_metadata = jsonb_set(
        COALESCE(user_message.message_metadata, '{}'::jsonb),
        '{request_status}',
        to_jsonb((
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM gg_messages AS response
                    WHERE response.thread_id = user_message.thread_id
                      AND response.request_id = user_message.request_id
                      AND response.message_type = 'system'
                      AND NULLIF(
                          BTRIM(COALESCE(response.message_metadata->>'error', '')),
                          ''
                      ) IS NOT NULL
                ) THEN 'failed'
                WHEN EXISTS (
                    SELECT 1
                    FROM gg_messages AS response
                    WHERE response.thread_id = user_message.thread_id
                      AND response.request_id = user_message.request_id
                      AND response.message_type = 'system'
                ) THEN 'completed'
                ELSE 'in_progress'
            END
        )::text),
        TRUE
    )
WHERE user_message.request_id IS NOT NULL
  AND user_message.message_type = 'user'
  AND user_message.message_metadata->>'request_status' IS NULL;
