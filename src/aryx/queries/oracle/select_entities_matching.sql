-- Oracle ADB 23ai: entity candidate selector for rule evaluation.
-- Replaces Postgres JSONB ? (key-exists) with JSON_EXISTS — Oracle does not
-- support the ? operator and _translate_sql does not translate it.
-- Params: :1=workspace_id :2=ontology_type_or_null :3=ontology_type_or_null
--         :4=attr_key_or_null :5=attr_key_or_null
SELECT id, ontology_type, attributes
FROM   aryx_entity
WHERE  workspace_id = :1
  AND  (:2 IS NULL OR ontology_type = :3)
  AND  (:4 IS NULL OR JSON_EXISTS(attributes, CONCAT('$.', :5)))
