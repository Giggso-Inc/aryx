-- Oracle ADB 23ai: relationships touching a set of entity IDs.
-- Replaces source_entity_id = ANY(%s) OR target_entity_id = ANY(%s).
-- CTE materialises JSON_TABLE once so :2 is bound only once (not twice).
-- Params: :1=workspace_id  :2=entity_ids_json
WITH ids AS (
  SELECT TO_NUMBER(jt.id_val) AS id
  FROM   JSON_TABLE(:2, '$[*]' COLUMNS (id_val VARCHAR2(40) PATH '$')) jt
)
SELECT source_entity_id, target_entity_id, name
FROM   aryx_relationship
WHERE  workspace_id = :1
  AND  (
         source_entity_id IN (SELECT id FROM ids)
         OR target_entity_id IN (SELECT id FROM ids)
       )
