-- Oracle ADB 23ai: upsert an Ask thread via MERGE. No RETURNING -- see
-- ask_thread_ensure_channel.sql's note; caller does a follow-up SELECT
-- (ask_thread_select_thread_row.sql).
-- TRIM(t.title) naturally becomes NULL for a blank/whitespace-only title
-- (Oracle has no true empty string), so no NULLIF is needed the way the
-- Postgres version needs NULLIF(title, '').
MERGE INTO gg_threads t
USING (
    SELECT :1 AS req_id, :2 AS req_title, :3 AS req_description, :4 AS req_channel_id
    FROM dual
) src
ON (t.id = src.req_id)
WHEN MATCHED THEN
    UPDATE SET
        t.title = COALESCE(TRIM(t.title), src.req_title),
        t.is_archived = 0,
        t.updated_at = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN
    -- message_count/ai_enabled/created_at/updated_at are NOT NULL with no
    -- DB-level default -- shay_backend/app/models/message.py's Thread class
    -- applies these at the SQLAlchemy ORM layer only (default=0/True/
    -- current_timestamp), which a raw INSERT never sees.
    INSERT (
        id, title, description, channel_id, is_active, is_archived,
        message_count, ai_enabled, created_at, updated_at
    )
    VALUES (
        src.req_id, src.req_title, src.req_description, src.req_channel_id,
        1, 0, 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
