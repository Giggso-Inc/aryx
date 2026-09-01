SELECT
    workflow_id::text,
    confirmation_id::text,
    actor_id,
    thread_id::text,
    status,
    current_step,
    request_payload,
    identifiers,
    steps,
    error_message,
    created_at,
    updated_at,
    completed_at
FROM aryx_sales_msi_workflow
WHERE confirmation_id = %s::uuid
LIMIT 1
