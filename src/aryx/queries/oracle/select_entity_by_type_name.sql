-- Oracle ADB 23ai: replace Postgres JSONB ->>'name' with JSON_VALUE.
-- ROWNUM in WHERE is evaluated before ORDER BY — use FETCH FIRST instead.
-- Params: :1=workspace_id  :2=ontology_type  :3=name_value
SELECT id
FROM aryx_entity
WHERE workspace_id = :1 AND ontology_type = :2
  AND JSON_VALUE(attributes, '$.name') = :3
ORDER BY id
FETCH FIRST 1 ROWS ONLY
