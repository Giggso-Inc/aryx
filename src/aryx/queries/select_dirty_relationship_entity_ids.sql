SELECT source_entity_id AS entity_id
FROM aryx_relationship
WHERE workspace_id = %s AND updated_at >= %s
UNION
SELECT target_entity_id AS entity_id
FROM aryx_relationship
WHERE workspace_id = %s AND updated_at >= %s
