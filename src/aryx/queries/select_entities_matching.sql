-- Candidate entities for rule evaluation.
-- Pushes ontology_type equality and attribute-key existence into SQL so only
-- matching rows reach Python. Pass NULL to skip a filter clause.
SELECT id, ontology_type, attributes
FROM   aryx_entity
WHERE  workspace_id = %s
  AND  (%s::text IS NULL OR ontology_type = %s)
  AND  (%s::text IS NULL OR attributes ? %s)
