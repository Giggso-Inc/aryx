DELETE FROM aryx_projected_entity p
WHERE p.workspace_id = %(workspace_id)s
  AND EXISTS (
    SELECT 1
    FROM aryx_entity e
    WHERE e.workspace_id = p.workspace_id
      AND e.id = p.entity_id
      AND NOT EXISTS (
        SELECT 1
        FROM aryx_entity_member m
        WHERE m.workspace_id = e.workspace_id
          AND m.entity_id = e.id
      )
  )
