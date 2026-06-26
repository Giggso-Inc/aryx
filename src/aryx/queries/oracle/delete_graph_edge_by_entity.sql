-- Oracle ADB 23ai: remove all edges where entity appears as source or target.
-- Params: :1=workspace_id  :2=entity_id
DELETE FROM aryx_graph_edge
WHERE workspace_id = :1 AND (src_id = :2 OR tgt_id = :2)
