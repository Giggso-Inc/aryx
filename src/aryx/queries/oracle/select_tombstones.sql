-- Oracle ADB 23ai: EXCEPT is not valid Oracle syntax -- MINUS is the
-- equivalent set-difference operator. Everything else matches the
-- Postgres version (select_tombstones.sql).
-- Params: :1=workspace_id  :2=workspace_id
SELECT p.entity_id
FROM   aryx_projected_entity p
WHERE  p.workspace_id = :1
MINUS
SELECT e.id
FROM   aryx_entity e
WHERE  e.workspace_id = :2
