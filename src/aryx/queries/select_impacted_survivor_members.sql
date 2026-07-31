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
  AND m.entity_id = ANY(%(entity_ids)s)
ORDER BY m.entity_id, l.id
