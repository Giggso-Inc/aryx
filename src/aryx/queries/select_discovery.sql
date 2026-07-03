SELECT discovery_id, workspace_id, status,
       data_json, summary_json, file_count,
       confirm_state, created_at, confirmed_at
FROM aryx_discovery
WHERE discovery_id = %s
  AND workspace_id = %s
