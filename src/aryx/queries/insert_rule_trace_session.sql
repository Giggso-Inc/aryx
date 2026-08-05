INSERT INTO aryx_rule_trace_session (run_id, workspace_id, catalog_prefix, file_key)
VALUES (%s, %s, %s, %s)
ON CONFLICT (run_id) DO NOTHING
