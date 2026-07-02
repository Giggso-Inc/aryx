-- Oracle ADB 23ai: upsert ontology type using MERGE with named bind vars.
-- Named vars (:workspace_id etc.) are deduplicated by name by oracledb thin,
-- so reuse across ON + UPDATE + VALUES clauses counts as one binding each.
-- Positional (:N) vars count per occurrence, causing DPY-4009 on reuse.
MERGE INTO aryx_ontology_type t
USING dual
ON (t.workspace_id = :workspace_id AND t.name = :name)
WHEN MATCHED THEN
    UPDATE SET t.attributes = :attributes, t.status = :status, t.source = :source
WHEN NOT MATCHED THEN
    INSERT (workspace_id, name, attributes, status, source)
    VALUES (:workspace_id, :name, :attributes, :status, :source)
