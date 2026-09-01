UPDATE aryx_mcp_token
SET allowed_tools = %s
WHERE id = %s AND revoked_at IS NULL AND purpose = 'sales_cpq'
RETURNING id, label
