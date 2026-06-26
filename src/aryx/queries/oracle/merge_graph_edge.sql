-- Oracle ADB 23ai: upsert a directed relationship edge between two entities.
-- Params: :ws=workspace_id  :src=src_id  :tgt=tgt_id  :name=name
MERGE INTO aryx_graph_edge t
USING (SELECT :ws AS workspace_id, :src AS src_id,
              :tgt AS tgt_id, :name AS name FROM dual) s
ON (t.workspace_id = s.workspace_id
    AND t.src_id = s.src_id
    AND t.tgt_id = s.tgt_id
    AND t.name = s.name)
WHEN NOT MATCHED THEN
    INSERT (workspace_id, src_id, tgt_id, name)
    VALUES (:ws, :src, :tgt, :name)
