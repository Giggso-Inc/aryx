SELECT m.entity_id, l.source_system, l.source_dataset, l.source_record_id
FROM aryx_entity_member m
JOIN aryx_entity e
  ON e.id = m.entity_id
 AND e.workspace_id = m.workspace_id
JOIN aryx_landed_record l
  ON l.id = m.landed_record_id
 AND l.workspace_id = m.workspace_id
WHERE m.workspace_id = %s
  AND e.ontology_type = ANY(%s)
ORDER BY m.entity_id, l.source_system, l.source_dataset, l.source_record_id;
