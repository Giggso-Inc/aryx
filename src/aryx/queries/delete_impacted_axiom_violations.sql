DELETE FROM aryx_axiom_violation
WHERE workspace_id = %(workspace_id)s
  AND entity_id = ANY(%(entity_ids)s)
