SELECT DISTINCT m.entity_id
FROM aryx_entity_member m
JOIN aryx_landed_record l
  ON l.workspace_id = m.workspace_id
 AND l.id = m.landed_record_id
WHERE m.workspace_id = %(workspace_id)s
  AND l.source_system = %(source_system)s
  AND l.source_dataset = %(source_dataset)s
