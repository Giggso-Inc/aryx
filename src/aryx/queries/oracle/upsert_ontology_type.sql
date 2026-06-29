-- Oracle ADB 23ai: upsert ontology type using MERGE.
-- Postgres ON CONFLICT (workspace_id, name) DO UPDATE is not valid Oracle SQL.
-- MERGE implements the same upsert semantics natively, with no constraint
-- violation — the ORA-00001 path is bypassed entirely.
-- Positional params match ontology_store.seed_types() tuple order:
--   :1=workspace_id  :2=name  :3=attributes  :4=status  :5=source
MERGE INTO aryx_ontology_type t
USING (SELECT :1 AS workspace_id, :2 AS name FROM dual) s
ON (t.workspace_id = s.workspace_id AND t.name = s.name)
WHEN MATCHED THEN
    UPDATE SET t.attributes = :3, t.status = :4, t.source = :5
WHEN NOT MATCHED THEN
    INSERT (workspace_id, name, attributes, status, source)
    VALUES (:1, :2, :3, :4, :5)
