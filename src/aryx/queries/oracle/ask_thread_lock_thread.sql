-- Oracle ADB 23ai: lock the thread row to serialize sequence_number
-- assignment for concurrent message inserts on the same thread (mirrors the
-- Postgres CTE's `SELECT id FROM gg_threads WHERE id = %s FOR UPDATE`).
-- Param: :1=thread id
SELECT id FROM gg_threads WHERE id = :1 FOR UPDATE
