UPDATE aryx_entity
SET attributes = %s,
    confidence = %s,
    updated_at = now()
WHERE id = %s
  AND workspace_id = %s
