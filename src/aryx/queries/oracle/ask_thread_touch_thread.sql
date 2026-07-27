-- Oracle ADB 23ai: Postgres's UPDATE ... FROM has no Oracle equivalent
-- (Oracle's UPDATE has no FROM clause) -- rewritten as correlated
-- subqueries in the SET clause, same pattern already used by
-- ask_thread_touch_channel.sql for an analogous case.
-- Params: :1=thread_id (message count scope) :2=thread_id (target row)
UPDATE gg_threads
SET message_count = (
        SELECT COUNT(*)
        FROM gg_messages
        WHERE gg_messages.thread_id = :1
          AND gg_messages.is_visible = 1
    ),
    last_message_at = (
        SELECT MAX(gg_messages.created_at)
        FROM gg_messages
        WHERE gg_messages.thread_id = :1
          AND gg_messages.is_visible = 1
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE gg_threads.id = :2
