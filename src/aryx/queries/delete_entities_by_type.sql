DELETE FROM aryx_entity
WHERE workspace_id = %s AND ontology_type = %s
RETURNING id
