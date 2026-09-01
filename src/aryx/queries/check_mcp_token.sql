SELECT
    id,
    purpose,
    allowed_tools,
    workspace_id,
    shay_workspace_id,
    expires_at
FROM aryx_mcp_token
WHERE token_hash = %s
  AND revoked_at IS NULL
  AND (expires_at IS NULL OR expires_at > now())
LIMIT 1
