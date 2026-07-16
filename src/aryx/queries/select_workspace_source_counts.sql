SELECT l.source_system, l.source_dataset, COUNT(*)
FROM aryx_entity_member m
JOIN aryx_landed_record l
  ON l.id = m.landed_record_id AND l.workspace_id = m.workspace_id
WHERE m.workspace_id = %(workspace_id)s
GROUP BY l.source_system, l.source_dataset
ORDER BY COUNT(*) DESC, l.source_system, l.source_dataset
