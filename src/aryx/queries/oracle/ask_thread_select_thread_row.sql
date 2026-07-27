-- Oracle ADB 23ai: fetch (id, title) after ask_thread_ensure_thread's MERGE.
-- Param: :1=thread id
SELECT id, title
FROM gg_threads
WHERE id = :1
FETCH FIRST 1 ROWS ONLY
