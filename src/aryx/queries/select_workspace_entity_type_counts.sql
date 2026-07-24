SELECT ontology_type, COUNT(*)
FROM aryx_entity
WHERE workspace_id = %(workspace_id)s
GROUP BY ontology_type
ORDER BY COUNT(*) DESC, ontology_type
