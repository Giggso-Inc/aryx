INSERT INTO aryx_sales_msi_workflow (
    workflow_id,
    confirmation_id,
    actor_id,
    thread_id,
    status,
    current_step,
    request_payload,
    identifiers,
    steps
)
VALUES (
    %s::uuid,
    %s::uuid,
    %s,
    %s::uuid,
    %s,
    %s,
    %s,
    %s,
    %s
)
ON CONFLICT (confirmation_id) DO NOTHING
RETURNING
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
