SELECT run_id, workspace_id, catalog_prefix, file_key, started_at
FROM aryx_rule_trace_session
WHERE status = 'open' AND started_at < %s
