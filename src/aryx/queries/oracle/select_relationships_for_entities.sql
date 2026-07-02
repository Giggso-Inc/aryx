-- Oracle ADB 23ai: relationships touching a set of entity IDs.
-- Replaces source_entity_id = ANY(%s) OR target_entity_id = ANY(%s).
-- _unwrap_params serialises each list to a JSON string; JSON_TABLE unpacks it.
-- :2 and :3 are intentionally separate params: source and target sets may
-- differ when callers filter by direction. Pass the same list for both to
-- find all relationships in either direction.
-- Params: :1=workspace_id  :2=source_entity_ids_json  :3=target_entity_ids_json
SELECT source_entity_id, target_entity_id, name
FROM   aryx_relationship
WHERE  workspace_id = :1
  AND  (
         source_entity_id IN (
           -- entities that appear as the source of a relationship
           SELECT TO_NUMBER(jt.id_val)
           FROM   JSON_TABLE(:2, '$[*]' COLUMNS (id_val VARCHAR2(40) PATH '$')) jt
         )
         OR target_entity_id IN (
           -- entities that appear as the target of a relationship
           SELECT TO_NUMBER(jt.id_val)
           FROM   JSON_TABLE(:3, '$[*]' COLUMNS (id_val VARCHAR2(40) PATH '$')) jt
         )
       )
