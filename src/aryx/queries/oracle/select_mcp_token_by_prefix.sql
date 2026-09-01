-- Oracle ADB 23ai: follow-up read after insert_mcp_token.sql (no RETURNING)
-- -- plain SELECT returns natively-typed columns, unlike RETURNING's
-- string-typed out-vars.
SELECT
    id,
    label,
    prefix,
    created_at,
    purpose,
    allowed_tools,
    workspace_id,
    shay_workspace_id,
    expires_at
FROM aryx_mcp_token
WHERE prefix = %s
