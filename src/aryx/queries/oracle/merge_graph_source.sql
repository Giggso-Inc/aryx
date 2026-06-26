-- Oracle ADB 23ai: upsert a graph source (system+dataset+record).
-- Params: :ws=workspace_id  :sys=system  :ds=dataset  :rid=record_id
MERGE INTO aryx_graph_source t
USING (SELECT :ws AS workspace_id, :sys AS system,
              :ds AS dataset, :rid AS record_id FROM dual) s
ON (t.workspace_id = s.workspace_id
    AND t.system = s.system
    AND t.dataset = s.dataset
    AND t.record_id = s.record_id)
WHEN NOT MATCHED THEN
    INSERT (workspace_id, system, dataset, record_id)
    VALUES (:ws, :sys, :ds, :rid)
