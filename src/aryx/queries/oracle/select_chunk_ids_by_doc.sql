-- Oracle override: uses JSON_TABLE to unnest the chunk_index list passed as a
-- JSON array string (:2). PostgreSQL uses chunk_index = ANY(%s) with a native
-- array; Oracle does not support that syntax so the list is serialised to
-- JSON by _unwrap_params.
SELECT id, chunk_index
FROM aryx_chunk
WHERE doc_id = :1
  AND chunk_index IN (
    SELECT TO_NUMBER(jt.idx_val)
    FROM JSON_TABLE(:2, '$[*]' COLUMNS (idx_val VARCHAR2(40) PATH '$')) jt
  )
