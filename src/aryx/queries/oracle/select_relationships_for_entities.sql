-- Oracle ADB 23ai: relationships touching a set of entity IDs.
-- Replaces source_entity_id = ANY(%s) OR target_entity_id = ANY(%s).
-- _unwrap_params serialises the list to a JSON string; JSON_TABLE unpacks it.
-- Params: :1=workspace_id  :2=entity_ids_json  :3=entity_ids_json (same list twice)
SELECT source_entity_id, target_entity_id, name
FROM   aryx_relationship
WHERE  workspace_id = :1
  AND  (
         source_entity_id IN (
           SELECT TO_NUMBER(jt.id_val)
           FROM   JSON_TABLE(:2, '$[*]' COLUMNS (id_val VARCHAR2(40) PATH '$')) jt
         )
         OR target_entity_id IN (
           SELECT TO_NUMBER(jt.id_val)
           FROM   JSON_TABLE(:3, '$[*]' COLUMNS (id_val VARCHAR2(40) PATH '$')) jt
         )
       )
