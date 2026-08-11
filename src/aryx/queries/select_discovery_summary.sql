SELECT summary_json
FROM aryx_discovery
WHERE discovery_id = %s
  AND workspace_id = %s
