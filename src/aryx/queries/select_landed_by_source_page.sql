SELECT id, payload, source_system, source_dataset, source_record_id
FROM aryx_landed_record
WHERE workspace_id = %(workspace_id)s
  AND source_system = %(source_system)s
  AND source_dataset = %(source_dataset)s
ORDER BY id
LIMIT %(limit)s OFFSET %(offset)s
