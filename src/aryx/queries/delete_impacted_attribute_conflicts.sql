DELETE FROM aryx_attribute_conflict
WHERE workspace_id = %(workspace_id)s
  AND entity_id = ANY(%(entity_ids)s)
