UPDATE aryx_entity
SET attributes = %s,
    confidence = COALESCE(%s, confidence),
    updated_at = now()
WHERE id = %s AND workspace_id = %s
RETURNING id, ontology_type, attributes, confidence, created_at, updated_at;
