DELETE FROM aryx_projected_entity
WHERE workspace_id = %(workspace_id)s
  AND entity_id = ANY(%(entity_ids)s)
