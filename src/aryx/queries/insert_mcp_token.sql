INSERT INTO aryx_mcp_token (
    label,
    token_hash,
    prefix,
    purpose,
    allowed_tools,
    workspace_id,
    shay_workspace_id,
    expires_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING
    id,
    label,
    prefix,
    created_at,
    purpose,
    allowed_tools,
    workspace_id,
    shay_workspace_id,
    expires_at
