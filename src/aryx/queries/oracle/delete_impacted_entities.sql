DELETE FROM aryx_entity
WHERE workspace_id = %(workspace_id)s
  AND id IN (
    SELECT ids.id
    FROM JSON_TABLE(
      %(entity_ids)s,
      '$[*]' COLUMNS (id NUMBER PATH '$')
    ) ids
  )
