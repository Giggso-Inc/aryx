SELECT id, workspace_id, name, kind, config_json, secret_mask, created_at
FROM aryx_datasource
WHERE workspace_id = %(workspace_id)s AND name = %(name)s
