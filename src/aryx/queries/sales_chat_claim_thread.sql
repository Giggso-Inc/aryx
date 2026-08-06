INSERT INTO aryx_sales_chat_thread (
    thread_id,
    actor_id,
    workspace_id,
    shay_workspace_id
)
VALUES (%s::uuid, %s, %s, %s::uuid)
ON CONFLICT (thread_id) DO NOTHING
RETURNING thread_id::text, actor_id, workspace_id, shay_workspace_id::text
