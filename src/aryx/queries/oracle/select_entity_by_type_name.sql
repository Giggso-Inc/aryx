-- Oracle ADB 23ai: replace Postgres JSONB ->>'name' with JSON_VALUE.
-- Params: :1=workspace_id  :2=ontology_type  :3=name_value
SELECT id
FROM aryx_entity
WHERE workspace_id = :1 AND ontology_type = :2
  AND JSON_VALUE(attributes, '$.name') = :3
  AND ROWNUM = 1
ORDER BY id
