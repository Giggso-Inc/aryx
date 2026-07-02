-- Oracle override: uses JSON_TABLE to unnest the ID list passed as a JSON array
-- string (:2). PostgreSQL uses id = ANY(%s) with a native array; Oracle does not
-- support that syntax so the list is serialised to JSON by _unwrap_params.
SELECT id, payload, source_system, cleaned_at
FROM aryx_landed_record
WHERE workspace_id = :1
  AND id IN (
    SELECT TO_NUMBER(jt.id_val)
    FROM JSON_TABLE(:2, '$[*]' COLUMNS (id_val VARCHAR2(40) PATH '$')) jt
  )
