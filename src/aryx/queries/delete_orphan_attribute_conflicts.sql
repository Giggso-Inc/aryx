DELETE FROM aryx_attribute_conflict c
WHERE c.workspace_id = %(workspace_id)s
  AND EXISTS (
    SELECT 1
    FROM aryx_entity e
    WHERE e.workspace_id = c.workspace_id
      AND e.id = c.entity_id
      AND NOT EXISTS (
        SELECT 1
        FROM aryx_entity_member m
        WHERE m.workspace_id = e.workspace_id
          AND m.entity_id = e.id
      )
  )
