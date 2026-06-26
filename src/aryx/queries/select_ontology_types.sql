SELECT name, attributes, status, source, parent_type,
       COALESCE(attribute_schema, '{}'::jsonb) AS attribute_schema
FROM aryx_ontology_type
WHERE workspace_id = %s
ORDER BY name
