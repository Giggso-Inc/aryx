UPDATE aryx_entity
SET attributes = %s,
    updated_at = now()
WHERE id = %s AND workspace_id = %s
RETURNING id, ontology_type, attributes
