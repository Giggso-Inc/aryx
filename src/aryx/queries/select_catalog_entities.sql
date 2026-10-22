SELECT id, ontology_type, attributes
FROM aryx_entity
WHERE workspace_id = %s
  AND ontology_type = ANY(%s)
ORDER BY ontology_type, id;
