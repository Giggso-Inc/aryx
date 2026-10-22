SELECT COUNT(*)
FROM aryx_entity
WHERE workspace_id = %s
  AND ontology_type = ANY(%s);
