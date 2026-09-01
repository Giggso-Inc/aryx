SELECT
    thread_id::text,
    actor_id,
    workspace_id,
    shay_workspace_id::text
FROM aryx_sales_chat_thread
WHERE thread_id = %s::uuid
LIMIT 1
