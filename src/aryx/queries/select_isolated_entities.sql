SELECT e.id, e.ontology_type, e.attributes
FROM aryx_entity e
WHERE e.workspace_id = %s
  AND NOT EXISTS (
      SELECT 1 FROM aryx_relationship r
      WHERE r.workspace_id = %s
        AND (r.source_entity_id = e.id OR r.target_entity_id = e.id)
  )
