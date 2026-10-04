DELETE FROM aryx_entity_member
WHERE workspace_id = %(workspace_id)s
  AND entity_id = ANY(%(entity_ids)s)
