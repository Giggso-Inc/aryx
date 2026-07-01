SELECT name, attributes, status, source, parent_type,
       COALESCE(attribute_schema, TO_CLOB('{}')) AS attribute_schema
  FROM aryx_ontology_type
 WHERE workspace_id = :1
 ORDER BY name
