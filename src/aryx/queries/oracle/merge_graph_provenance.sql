-- Oracle ADB 23ai: link an entity to a source record (provenance edge).
-- Params: :ws=workspace_id  :eid=entity_id  :sid=source_id
MERGE INTO aryx_graph_provenance t
USING (SELECT :ws AS workspace_id, :eid AS entity_id,
              :sid AS source_id FROM dual) s
ON (t.workspace_id = s.workspace_id
    AND t.entity_id = s.entity_id
    AND t.source_id = s.source_id)
WHEN NOT MATCHED THEN
    INSERT (workspace_id, entity_id, source_id)
    VALUES (:ws, :eid, :sid)
