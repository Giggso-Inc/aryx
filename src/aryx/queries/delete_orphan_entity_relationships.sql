DELETE FROM aryx_relationship r
WHERE r.workspace_id = %(workspace_id)s
  AND (
    EXISTS (
      SELECT 1
      FROM aryx_entity e
      WHERE e.workspace_id = r.workspace_id
        AND e.id = r.source_entity_id
        AND NOT EXISTS (
          SELECT 1
          FROM aryx_entity_member m
          WHERE m.workspace_id = e.workspace_id
            AND m.entity_id = e.id
        )
    )
    OR EXISTS (
      SELECT 1
      FROM aryx_entity e
      WHERE e.workspace_id = r.workspace_id
        AND e.id = r.target_entity_id
        AND NOT EXISTS (
          SELECT 1
          FROM aryx_entity_member m
          WHERE m.workspace_id = e.workspace_id
            AND m.entity_id = e.id
        )
    )
  )
