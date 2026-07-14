WITH page AS (
    SELECT
        id::text,
        message_type,
        content,
        sequence_number,
        created_at,
        message_metadata,
        citations,
        usage_metrics
    FROM gg_messages
    WHERE thread_id = %s::uuid
      AND (%s::int IS NULL OR sequence_number < %s::int)
      AND message_type IN ('user', 'system')
      AND is_visible = TRUE
    ORDER BY sequence_number DESC
    LIMIT %s
)
SELECT
    id,
    message_type,
    content,
    sequence_number,
    created_at,
    message_metadata,
    citations,
    usage_metrics
FROM page
ORDER BY sequence_number ASC
