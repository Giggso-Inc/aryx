-- Oracle equivalent of sales_chat_select_thread.sql. All 4 columns are
-- VARCHAR2/NUMBER on Oracle (no native uuid type) -- no casts needed.
-- Params: :1=thread_id
SELECT
    thread_id,
    actor_id,
    workspace_id,
    shay_workspace_id
FROM aryx_sales_chat_thread
WHERE thread_id = :1
FETCH FIRST 1 ROWS ONLY
