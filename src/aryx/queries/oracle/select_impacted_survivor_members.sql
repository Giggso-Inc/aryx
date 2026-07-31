SELECT m.entity_id,
       l.id,
       l.payload,
       l.source_system,
       l.cleaned_at
FROM aryx_entity_member m
JOIN aryx_landed_record l
  ON l.workspace_id = m.workspace_id
 AND l.id = m.landed_record_id
WHERE m.workspace_id = %(workspace_id)s
  AND m.entity_id IN (
    SELECT ids.id
    FROM JSON_TABLE(
      %(entity_ids)s,
      '$[*]' COLUMNS (id NUMBER PATH '$')
    ) ids
  )
ORDER BY m.entity_id, l.id
