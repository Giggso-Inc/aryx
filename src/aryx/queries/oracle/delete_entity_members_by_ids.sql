DELETE FROM aryx_entity_member
WHERE workspace_id = %(workspace_id)s
  AND entity_id IN (
    SELECT ids.id
    FROM JSON_TABLE(
      %(entity_ids)s,
      '$[*]' COLUMNS (id NUMBER PATH '$')
    ) ids
  )
