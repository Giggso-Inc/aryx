SELECT
    id,
    label,
    prefix,
    created_at,
    last_used_at,
    revoked_at,
    purpose,
    allowed_tools,
    workspace_id,
    shay_workspace_id,
    expires_at
FROM aryx_mcp_token
ORDER BY created_at DESC
