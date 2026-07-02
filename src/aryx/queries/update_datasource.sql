UPDATE aryx_datasource
SET name = %(name)s,
    kind = %(kind)s,
    config_json = %(config_json)s::jsonb,
    secret_cipher = COALESCE(%(secret_cipher)s, secret_cipher),
    secret_mask = COALESCE(%(secret_mask)s, secret_mask)
WHERE id = %(id)s
RETURNING id, workspace_id, name, kind, config_json, secret_mask, created_at
