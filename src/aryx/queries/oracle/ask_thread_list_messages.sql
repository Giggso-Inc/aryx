-- Oracle ADB 23ai override.
-- gg_messages' request-tracking column is named QUERY_ID on this schema
-- (matches Shay's SQLAlchemy model, message.py) even though the Postgres
-- side of this feature calls it request_id -- confirmed live via
-- USER_TAB_COLUMNS, not a naming choice made here. Every ask_thread query
-- touching this column needs the same rename.
-- is_visible is NUMBER(0/1) here (SQLAlchemy's Oracle Boolean), not TRUE/FALSE.
WITH page AS (
    SELECT
        id,
        message_type,
        content,
        sequence_number,
        query_id,
        created_at,
        message_metadata,
        citations,
        usage_metrics
    FROM gg_messages
    WHERE thread_id = :1
      AND (:2 IS NULL OR sequence_number < :3)
      AND message_type IN ('user', 'system')
      AND is_visible = 1
    ORDER BY sequence_number DESC
    FETCH FIRST :4 ROWS ONLY
)
SELECT
    id, message_type, content, sequence_number, query_id,
    created_at, message_metadata, citations, usage_metrics
FROM page
ORDER BY sequence_number ASC
