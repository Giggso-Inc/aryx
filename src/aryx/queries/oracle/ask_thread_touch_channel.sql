-- Oracle equivalent of ask_thread_touch_channel.sql -- see that file's
-- caller (ask_thread_store.py) for the newly_inserted guard around this
-- call. gg_channels.id is VARCHAR2(36) on Oracle (Shay's UUID column),
-- no cast needed. NOW() -> CURRENT_TIMESTAMP, matching
-- ask_thread_touch_thread.sql's own Oracle override convention.
UPDATE gg_channels
SET message_count = message_count + 1,
    last_message_at = CURRENT_TIMESTAMP,
    updated_at = CURRENT_TIMESTAMP
WHERE id = :1
