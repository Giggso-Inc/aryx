-- Oracle ADB 23ai: provenance for a set of entities.
-- Replaces entity_id = ANY(%s) — Oracle has no ANY() operator.
-- _unwrap_params serialises the list to a JSON string; JSON_TABLE unpacks it.
-- Params: :1=workspace_id  :2=entity_ids (JSON array string)
SELECT m.entity_id, r.source_system, r.source_dataset, r.source_record_id
FROM   aryx_entity_member m
JOIN   aryx_landed_record r ON r.id = m.landed_record_id
WHERE  m.workspace_id = :1
  AND  m.entity_id IN (
         SELECT TO_NUMBER(jt.id_val)
         FROM   JSON_TABLE(:2, '$[*]' COLUMNS (id_val VARCHAR2(40) PATH '$')) jt
       )
