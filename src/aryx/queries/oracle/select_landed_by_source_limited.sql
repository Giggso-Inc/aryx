SELECT id, payload, source_system, source_dataset, source_record_id
FROM aryx_landed_record
WHERE workspace_id = %s
  AND source_system = %s
  AND source_dataset = %s
ORDER BY id
FETCH FIRST %s ROWS ONLY
