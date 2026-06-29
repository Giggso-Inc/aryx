UPDATE aryx_ontology_type
   SET attribute_schema = :1
 WHERE workspace_id = :2
   AND name = :3
