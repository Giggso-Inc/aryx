DELETE FROM aryx_relationship
WHERE workspace_id = %(workspace_id)s
  AND (
    source_entity_id IN (
      SELECT ids.id
      FROM JSON_TABLE(
        %(entity_ids)s,
        '$[*]' COLUMNS (id NUMBER PATH '$')
      ) ids
    )
    OR target_entity_id IN (
      SELECT ids.id
      FROM JSON_TABLE(
        %(entity_ids)s,
        '$[*]' COLUMNS (id NUMBER PATH '$')
      ) ids
    )
  )
