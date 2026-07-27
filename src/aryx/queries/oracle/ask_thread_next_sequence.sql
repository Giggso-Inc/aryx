-- Oracle ADB 23ai: next sequence_number for a new message in this thread.
-- Safe against concurrent inserts because the caller holds the thread's row
-- lock (ask_thread_lock_thread.sql) for the duration of this transaction.
-- Param: :1=thread_id
SELECT COALESCE(MAX(sequence_number), 0) + 1
FROM gg_messages
WHERE thread_id = :1
