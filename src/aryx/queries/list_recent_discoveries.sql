SELECT discovery_id, status, summary_json, file_count, created_at, confirmed_at
FROM aryx_discovery
WHERE workspace_id = %s
ORDER BY created_at DESC
FETCH FIRST %s ROWS ONLY
