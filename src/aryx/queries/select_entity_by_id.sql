SELECT id, ontology_type, attributes
FROM aryx_entity
WHERE id = %s AND workspace_id = %s
