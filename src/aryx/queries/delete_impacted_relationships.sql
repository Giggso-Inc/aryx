DELETE FROM aryx_relationship
WHERE workspace_id = %(workspace_id)s
  AND (
    source_entity_id = ANY(%(entity_ids)s)
    OR target_entity_id = ANY(%(entity_ids)s)
  )
