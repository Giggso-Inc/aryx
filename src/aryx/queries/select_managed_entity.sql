SELECT id, ontology_type, attributes, confidence, created_at, updated_at
FROM aryx_entity
WHERE id = %s AND workspace_id = %s;
