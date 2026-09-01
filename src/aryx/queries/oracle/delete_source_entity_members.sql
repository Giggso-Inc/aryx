DELETE FROM aryx_entity_member m
WHERE m.workspace_id = %(workspace_id)s
  AND EXISTS (
    SELECT 1
    FROM aryx_landed_record l
    WHERE l.workspace_id = m.workspace_id
      AND l.id = m.landed_record_id
      AND l.source_system = %(source_system)s
      AND l.source_dataset = %(source_dataset)s
  )
