UPDATE aryx_entity
SET attributes = %s,
    confidence = %s,
    updated_at = CURRENT_TIMESTAMP
WHERE id = %s
  AND workspace_id = %s
