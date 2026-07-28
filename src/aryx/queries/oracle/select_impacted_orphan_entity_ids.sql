SELECT e.id
FROM aryx_entity e
WHERE e.workspace_id = %(workspace_id)s
  AND e.id IN (
    SELECT ids.id
    FROM JSON_TABLE(
      %(entity_ids)s,
      '$[*]' COLUMNS (id NUMBER PATH '$')
    ) ids
  )
  AND NOT EXISTS (
    SELECT 1
    FROM aryx_entity_member m
    WHERE m.workspace_id = e.workspace_id
      AND m.entity_id = e.id
  )
