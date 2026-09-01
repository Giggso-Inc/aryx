-- Oracle ADB 23ai: no RETURNING here -- the generic translator's RETURNING
-- mechanism types every out-var as oracledb.STRING with no outconverter,
-- so created_at/expires_at (TIMESTAMPTZ) and workspace_id (NUMBER) would
-- come back as raw Oracle-formatted strings instead of native types
-- (found by post-merge review). Caller does a follow-up SELECT by prefix
-- (select_mcp_token_by_prefix.sql), same technique used elsewhere in this
-- codebase for the same class of problem.
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
