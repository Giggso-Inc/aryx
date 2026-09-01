UPDATE aryx_sales_msi_workflow
SET status = %s,
    current_step = %s,
    identifiers = %s,
    steps = %s,
    error_message = %s,
    updated_at = now(),
    completed_at = CASE
        WHEN %s IN ('success', 'error') THEN COALESCE(completed_at, now())
        ELSE completed_at
    END
WHERE workflow_id = %s::uuid
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
